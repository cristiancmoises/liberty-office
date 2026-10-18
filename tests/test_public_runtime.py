"""A maintenance runtime can serve public code without opening account state."""

import hashlib
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from liberty.config import Settings
from liberty.public_assets import build_public_manifest

JS = "wordcraft-web-8f83828293ff7c4d.js"
WASM = "wordcraft-web-8f83828293ff7c4d_bg.wasm"


@pytest.fixture
def public_runtime(tmp_path, monkeypatch):
    from liberty import app, db, locks, security

    def forbidden(*args, **kwargs):
        raise AssertionError("Public delivery opened private state")

    for module, name in (
        (app, "Service"),
        (app, "DB"),
        (app, "VolumeLock"),
        (security, "Service"),
        (db, "DB"),
        (locks, "VolumeLock"),
    ):
        monkeypatch.setattr(module, name, forbidden)
    from liberty.public_app import create_public_app

    settings = Settings(
        data_dir=tmp_path / "absent",
        apps_dir=tmp_path / "apps",
        source_archive=tmp_path / "source.zip",
    )
    native = settings.apps_dir / "wordcraft"
    native.mkdir(parents=True)
    (native / "index.html").write_text(
        '<html><head></head><body><script type="module">start()</script></body></html>'
    )
    files = {JS: b"export const version=1;", WASM: b"\0asm\x01\0\0\0"}
    for name, data in files.items():
        (native / name).write_bytes(data)
    (native / "installed.json").write_text(
        json.dumps(
            {
                "id": "wordcraft",
                "version": "v0.7.0",
                "files": {
                    name: hashlib.sha256(data).hexdigest()
                    for name, data in files.items()
                },
            }
        )
    )
    manifest = build_public_manifest(settings.apps_dir, tmp_path / "public")
    settings = replace(settings, public_assets_dir=tmp_path / "public")
    settings.source_archive.write_bytes(b"synthetic source offer")
    application = create_public_app(settings)
    with TestClient(application, base_url=settings.origin) as client:
        yield application, client, settings, manifest
    assert not settings.data_dir.exists()


def test_public_runtime_never_opens_private_state(public_runtime):
    app, client, settings, manifest = public_runtime
    assert not hasattr(app.state, "svc")
    assert not settings.data_dir.exists()
    portal = (
        "/",
        "/demo",
        "/demo/apps",
        "/source.zip",
        "/healthz",
        "/static/maintenance.mjs",
        "/static/demo.mjs",
        "/static/fonts.css",
        "/static/bridge.mjs",
    )
    isolated = (
        "/demo/controller",
        "/demo/controller-assets/demo-session.mjs",
        "/demo/runtime/wordcraft/index.html",
        "/demo/runtime/wordcraft/__liberty/demo-host.mjs",
    )
    for origin, paths in (
        (settings.origin, portal),
        (settings.demo_editor_origin, isolated),
    ):
        for path in paths:
            for method in (client.get, client.head):
                response = method(origin + path)
                assert response.status_code == 200, (path, response.text)
                assert response.headers["cache-control"] == "no-store"
                assert "set-cookie" not in response.headers
    assert client.head("/demo").content == b""
    health = client.get("/healthz").json()
    assert health["mode"] == "public-only"
    assert health["generation"] == manifest["generation"]
    source = client.get("/source.zip")
    assert source.content == b"synthetic source offer"
    apps = client.get("/demo/apps").json()["apps"]
    assert len(apps) == 13
    assert next(item for item in apps if item["id"] == "wordcraft")["installed"]
    html = client.get(settings.demo_editor_origin + isolated[2]).text
    assert "demo-host.mjs" in html and "editor-host.mjs" not in html


@pytest.mark.parametrize(
    "path",
    ["/api/auth/status", "/api/files", "/api/admin/users", "/runtime/token/index.html"],
)
def test_private_routes_are_explicit_account_maintenance_only_on_portal(
    public_runtime, path
):
    _, client, settings, _ = public_runtime
    response = client.get(path)
    assert response.status_code == 503
    assert "account" in response.json()["detail"].lower()
    assert "retry-after" not in response.headers
    for origin in (settings.editor_origin, settings.demo_editor_origin):
        assert client.get(origin + path).status_code == 404


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_public_runtime_does_not_accept_mutations_or_preflights(public_runtime, method):
    _, client, settings, _ = public_runtime
    for origin in (
        settings.origin,
        settings.demo_editor_origin,
        settings.editor_origin,
    ):
        for path in ("/", "/demo", "/api/files", "/demo/controller"):
            response = client.request(method, origin + path, content=b"never stored")
            assert response.status_code in (404, 503)
            assert response.headers["cache-control"] == "no-store"


def test_public_runtime_enforces_exact_host_and_origin_boundaries(public_runtime):
    _, client, settings, _ = public_runtime
    for host in ("evil.invalid", "localhost:8888", "localhost:8097.evil.invalid"):
        assert client.get("/", headers={"Host": host}).status_code == 400
    for path in (
        "/",
        "/demo",
        "/demo/apps",
        "/source.zip",
        "/healthz",
        "/static/demo.mjs",
    ):
        assert client.get(settings.editor_origin + path).status_code == 404
    for path in ("/", "/demo", "/demo/apps", "/source.zip", "/static/demo.mjs"):
        assert client.get(settings.demo_editor_origin + path).status_code == 404
    for path in (
        "/demo/controller",
        "/demo/controller-assets/demo-session.mjs",
        "/demo/runtime/wordcraft/index.html",
    ):
        assert client.get(path).status_code == 404
    headers = client.get(settings.demo_editor_origin + "/healthz").headers
    assert "frame-ancestors " + settings.origin in headers["content-security-policy"]
    assert "clipboard-read=()" in headers["permissions-policy"]
    assert client.get("/").headers["x-frame-options"] == "DENY"


def test_public_runtime_closed_paths_integrity_and_symlink_denial(
    public_runtime, tmp_path
):
    _, client, settings, manifest = public_runtime
    base = settings.demo_editor_origin + "/demo/runtime/wordcraft/"
    for path in (
        "/static/app.js",
        "/static/index.html",
        "/static/editor-host.mjs",
        "/static/../config.py",
        "/static/%2e%2e%2fconfig.py",
        "/docs",
        "/openapi.json",
        "/unknown",
    ):
        assert client.get(path).status_code == 404
    for asset in (
        "../mfa.key",
        "%2e%2e%2fmfa.key",
        "sw.js",
        "installed.json",
        ".secret",
        "__liberty/editor-host.mjs",
    ):
        assert client.get(base + asset).status_code == 404
    outside = tmp_path / "outside.js"
    outside.write_text("private bytes")
    (settings.apps_dir / "wordcraft/linked.js").symlink_to(outside)
    (settings.apps_dir / "wordcraft/inside.js").symlink_to(
        settings.apps_dir / "wordcraft" / JS
    )
    for name in ("linked.js", "inside.js"):
        assert client.get(base + name).status_code == 404
    prefix = "/public-assets/" + manifest["generation"] + "/wordcraft/"
    response = client.get(prefix + JS, headers={"Accept-Encoding": "identity"})
    assert response.status_code == 200
    assert response.headers["cache-control"].endswith("immutable")
    assert client.head(prefix + JS).status_code == 200
    assert (
        client.get(prefix.replace(manifest["generation"], "0" * 64) + JS).status_code
        == 404
    )
    (settings.public_assets_dir / manifest["generation"] / "wordcraft" / JS).write_text(
        "tampered"
    )
    assert client.get(prefix + JS).status_code == 404


def test_public_health_without_a_generation_and_missing_source_stay_data_free(tmp_path):
    from liberty.public_app import create_public_app

    settings = Settings(
        data_dir=tmp_path / "absent", source_archive=tmp_path / "missing"
    )
    with TestClient(create_public_app(settings), base_url=settings.origin) as client:
        assert client.get("/healthz").json()["generation"] is None
        assert client.get("/source.zip").status_code == 404
    assert not settings.data_dir.exists()


def test_public_runtime_rejects_symlinked_editor_roots(public_runtime):
    _, client, settings, _ = public_runtime
    native = settings.apps_dir / "wordcraft"
    original = settings.apps_dir / "original-wordcraft"
    native.rename(original)
    native.symlink_to(original, target_is_directory=True)
    assert (
        client.get(
            settings.demo_editor_origin + "/demo/runtime/wordcraft/index.html"
        ).status_code
        == 404
    )


def test_maintenance_message_is_localized_without_creating_a_session(public_runtime):
    _, client, _, _ = public_runtime
    response = client.post(
        "/api/auth/login", headers={"Accept-Language": "pt-BR"}, content=b"not consumed"
    )
    assert response.status_code == 503
    assert (
        response.json()["detail"]
        == "As contas e o salvamento estão em manutenção. A demonstração pública continua disponível."
    )
    assert response.headers["content-language"] == "pt-BR"
    assert "set-cookie" not in response.headers


def test_public_code_keeps_both_generations_on_all_origins_without_private_routes(
    public_runtime,
):
    from liberty.public_app import create_public_app

    _, _, settings, previous = public_runtime
    native = settings.apps_dir / "wordcraft"
    data = b"export const version=2;"
    (native / JS).write_bytes(data)
    installed = json.loads((native / "installed.json").read_text())
    installed["files"][JS] = hashlib.sha256(data).hexdigest()
    (native / "installed.json").write_text(json.dumps(installed))
    current = build_public_manifest(settings.apps_dir, settings.public_assets_dir)
    assert current["generation"] != previous["generation"]
    with TestClient(create_public_app(settings), base_url=settings.origin) as client:
        for origin in (
            settings.origin,
            settings.demo_editor_origin,
            settings.editor_origin,
        ):
            for generation in (previous["generation"], current["generation"]):
                url = origin + "/public-assets/" + generation + "/wordcraft/" + JS
                response = client.get(url, headers={"Accept-Encoding": "identity"})
                assert response.status_code == 200
                assert response.headers["cache-control"].endswith("immutable")
                assert "set-cookie" not in response.headers
                assert client.head(url).status_code == 200
                assert client.get(url.replace(generation, "0" * 64)).status_code == 404
                for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
                    assert (
                        client.request(method, url, content=b"denied").status_code
                        == 404
                    )
            for path in (
                "/runtime/token/index.html",
                "/api/auth/status",
                "/static/editor-host.mjs",
            ):
                assert client.get(settings.editor_origin + path).status_code == 404
        target = settings.public_assets_dir / current["generation"] / "wordcraft" / JS
        target.write_bytes(b"tampered")
        assert (
            client.get(
                settings.editor_origin
                + "/public-assets/"
                + current["generation"]
                + "/wordcraft/"
                + JS
            ).status_code
            == 404
        )
