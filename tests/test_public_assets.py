import gzip
import hashlib
import json
from dataclasses import replace

import pytest
from conftest import activate, bootstrap, csrf, invite
from fastapi.testclient import TestClient

from liberty.app import create_app

JS = "wordcraft-web-8f83828293ff7c4d.js"
WASM = "wordcraft-web-8f83828293ff7c4d_bg.wasm"
SW_REGISTRATION = """if ("serviceWorker" in navigator && !new URLSearchParams(location.search).has("nosw")) {
  navigator.serviceWorker.register("sw.js").catch((e) => console.warn("service worker:", e));
}"""


def test_public_assets_setting_preserves_existing_positional_configuration(tmp_path):
    from liberty.config import Settings

    settings = Settings(
        tmp_path / "data",
        tmp_path / "apps",
        tmp_path / "source.zip",
        "http://localhost:9870",
    )
    assert settings.origin == "http://localhost:9870"
    assert settings.public_assets_dir is None


def installed(root, value=b"export const version=1;"):
    app = root / "wordcraft"
    app.mkdir(parents=True, exist_ok=True)
    (app / JS).write_bytes(value)
    (app / WASM).write_bytes(b"\x00asm\x01\x00\x00\x00")
    (app / "index.html").write_text(
        '<html><head><link rel="modulepreload" href="./'
        + JS
        + '" integrity="sha384-preserved"></head><body><script type="module">'
        + 'import init from "./'
        + JS
        + '"; init("./'
        + WASM
        + '");</script></body></html>'
    )
    files = {}
    for name in [JS, WASM]:
        data = (app / name).read_bytes()
        files[name] = hashlib.sha256(data).hexdigest()
        (app / (name + ".gz")).write_bytes(gzip.compress(data, mtime=0))
    (app / "installed.json").write_text(
        json.dumps({"id": "wordcraft", "version": "v0.7.0", "files": files})
    )
    return app


@pytest.fixture
def public_env(env, tmp_path):
    from liberty.assets import build_public_manifest

    _, _, settings = env
    installed(settings.apps_dir)
    store = tmp_path / "public-code"
    manifest = build_public_manifest(settings.apps_dir, store)
    configured = replace(
        settings, data_dir=tmp_path / "public-test-data", public_assets_dir=store
    )
    with TestClient(
        create_app(configured),
        base_url=settings.origin,
        headers={"Origin": settings.origin},
    ) as client:
        yield client, configured, store, manifest


def test_unsafe_native_service_worker_is_not_delivered_or_registered(env):
    _, client, settings = env
    app = settings.apps_dir / "effectcraft"
    app.mkdir(parents=True)
    (app / "index.html").write_text(
        "<html><head></head><body><script>"
        + SW_REGISTRATION
        + "</script></body></html>"
    )
    (app / "sw.js").write_text('self.addEventListener("fetch", cacheEverything);')
    base = settings.demo_editor_origin + "/demo/runtime/effectcraft/"
    html = client.get(base + "index.html")
    assert html.status_code == 200
    assert "serviceWorker.register" not in html.text
    assert client.get(base + "sw.js").status_code == 404


def test_only_manifested_public_code_is_immutable(public_env):
    client, settings, store, manifest = public_env
    prefix = "/public-assets/" + manifest["generation"] + "/wordcraft/"
    for origin in [
        settings.origin,
        settings.demo_editor_origin,
        settings.editor_origin,
    ]:
        response = client.get(
            origin + prefix + JS, headers={"Accept-Encoding": "identity"}
        )
        assert (
            response.status_code == 200
            and response.content == b"export const version=1;"
        )
        assert (
            response.headers["cache-control"] == "public, max-age=31536000, immutable"
        )
        assert response.headers["vary"] == "Accept-Encoding"
        assert "javascript" in response.headers["content-type"]
        head = client.head(origin + prefix + JS)
        assert head.status_code == 200 and head.content == b""
        for extra, status in [
            ({"If-None-Match": response.headers["etag"]}, 304),
            ({"Range": "bytes=0-5"}, 206),
        ]:
            selected = client.get(
                origin + prefix + JS, headers={"Accept-Encoding": "identity"} | extra
            )
            assert selected.status_code == status
            assert (
                selected.headers["cache-control"]
                == "public, max-age=31536000, immutable"
            )
    for path in [
        "index.html",
        "installed.json",
        ".env",
        "../liberty.db",
        "%2e%2e%2fliberty.db",
        "settings.js",
        "document.docx",
        "__liberty/demo-host.mjs",
        "sw.js",
        JS + ".gz",
    ]:
        response = client.get(settings.demo_editor_origin + prefix + path)
        assert response.status_code == 404
        assert response.headers["cache-control"] == "no-store"
    assert (
        client.get(
            settings.demo_editor_origin
            + prefix.replace(manifest["generation"], "0" * 64)
            + JS
        ).status_code
        == 404
    )
    assert (
        client.get(
            settings.demo_editor_origin + prefix + JS, params={"cache": "public"}
        ).status_code
        == 200
    )
    assert (
        client.get(settings.demo_editor_origin + "/api/auth/status").status_code == 404
    )
    target = store / manifest["generation"] / "wordcraft" / JS
    target.write_bytes(b"changed after packaging")
    response = client.get(
        settings.demo_editor_origin + prefix + JS,
        headers={"Accept-Encoding": "identity"},
    )
    assert (
        response.status_code == 404 and response.headers["cache-control"] == "no-store"
    )


def test_generations_coexist_without_silent_fallback(public_env):
    from liberty.assets import build_public_manifest
    from liberty.public_assets import load_public_generations

    client, settings, store, old = public_env
    installed(settings.apps_dir, b"export const version=2;")
    new = build_public_manifest(settings.apps_dir, store)
    assert old["generation"] != new["generation"]
    client.app.state.public_assets = load_public_generations(store)
    for manifest, content in [
        (old, b"export const version=1;"),
        (new, b"export const version=2;"),
    ]:
        url = (
            settings.demo_editor_origin
            + "/public-assets/"
            + manifest["generation"]
            + "/wordcraft/"
            + JS
        )
        assert (
            client.get(url, headers={"Accept-Encoding": "identity"}).content == content
        )
    assert (
        client.get(
            settings.demo_editor_origin
            + "/public-assets/"
            + "f" * 64
            + "/wordcraft/"
            + JS
        ).status_code
        == 404
    )


def test_packaging_uses_verified_inventory_not_arbitrary_code_or_configuration(
    tmp_path,
):
    from liberty.assets import build_public_manifest, load_public_manifest

    root, store = tmp_path / "apps", tmp_path / "public-code"
    app = installed(root)
    for name in ["settings.js", "private.json", "liberty.db", ".env", "sw.js"]:
        (app / name).write_text("must not become a public resource")
    manifest = build_public_manifest(root, store)
    assert set(manifest["apps"]["wordcraft"]) == {JS, WASM}
    path = store / manifest["generation"] / "manifest.json"
    assert load_public_manifest(path) == manifest
    manifest["apps"]["wordcraft"][JS]["representations"]["identity"]["sha256"] = (
        "0" * 64
    )
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        load_public_manifest(path)


def test_self_consistent_generation_hash_cannot_publish_an_unreviewed_path(tmp_path):
    from liberty.assets import build_public_manifest, load_public_manifest

    apps, store = tmp_path / "apps", tmp_path / "public-code"
    installed(apps)
    manifest = build_public_manifest(apps, store)
    old = store / manifest["generation"]
    (old / "wordcraft/private-config.js").write_bytes(b"private")
    manifest["apps"]["wordcraft"]["private-config.js"] = {
        "mime": "text/javascript",
        "representations": {
            "identity": {"sha256": hashlib.sha256(b"private").hexdigest(), "size": 7}
        },
    }
    payload = {"schema": manifest["schema"], "apps": manifest["apps"]}
    manifest["generation"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    destination = store / manifest["generation"]
    old.rename(destination)
    (destination / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="unreviewed"):
        load_public_manifest(destination / "manifest.json")


@pytest.mark.parametrize(
    "failure", ["base-hash", "gzip-content", "symlink", "directory-symlink"]
)
def test_packaging_rejects_unverified_bytes_and_symlinks(tmp_path, failure):
    from liberty.assets import build_public_manifest

    root, store = tmp_path / "apps", tmp_path / "public-code"
    app = installed(root)
    if failure == "base-hash":
        (app / JS).write_bytes(b"not the verified source")
    elif failure == "gzip-content":
        (app / (JS + ".gz")).write_bytes(gzip.compress(b"different source", mtime=0))
    elif failure == "symlink":
        (app / JS).unlink()
        private = tmp_path / "private.js"
        private.write_bytes(b"private")
        (app / JS).symlink_to(private)
    else:
        app.rename(root / "elsewhere")
        app.symlink_to(root / "elsewhere", target_is_directory=True)
    with pytest.raises(ValueError):
        build_public_manifest(root, store)


def test_public_code_never_contains_session_config_or_bypasses_private_tickets(
    public_env,
):
    client, settings, _, manifest = public_env
    bootstrap(client, settings)
    first = client.post("/api/editors/wordcraft", headers=csrf(client)).json()
    invitation = invite(client, username="viewer")
    activate(client, invitation["token"])
    second = client.post("/api/editors/wordcraft", headers=csrf(client)).json()
    for ticket in [first, second]:
        html = client.get(ticket["url"])
        assert html.status_code == 200 and html.headers["cache-control"] == "no-store"
        assert "/public-assets/" + manifest["generation"] + "/wordcraft/" in html.text
        assert 'src="./__liberty/editor-host.mjs"' in html.text
        assert "sha384-preserved" in html.text
        config = html.text.split('id="__liberty-config" type="application/json">')[
            1
        ].split("</script>")[0]
        assert json.loads(config)["nonce"] == ticket["nonce"]
    prefix = (
        settings.editor_origin
        + "/public-assets/"
        + manifest["generation"]
        + "/wordcraft/"
    )
    assert "__liberty-config" not in client.get(prefix + JS).text
    for name in ["index.html", "liberty.db", "blobs/file", "mfa.key", first["nonce"]]:
        assert client.get(prefix + name).status_code == 404
    assert (
        client.get(settings.origin + "/api/auth/status").headers["cache-control"]
        == "no-store"
    )
    assert (
        client.get(
            settings.demo_editor_origin + "/demo/runtime/wordcraft/index.html"
        ).headers["cache-control"]
        == "no-store"
    )
    client.delete("/api/editors/" + second["ticket_id"], headers=csrf(client))
    assert client.get(first["url"]).status_code == 200
    assert client.get(second["url"]).status_code == 401
