"""Image replacement must retain verified code for already-open editor tabs."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from test_public_assets import JS, installed

from liberty.public_app import create_public_app
from liberty.public_assets import build_public_manifest, load_public_generations


def test_fresh_image_store_serves_old_and_current_code_on_every_origin(env, tmp_path):
    _, _, settings = env
    old_apps, old_store = tmp_path / "old-apps", tmp_path / "old-image-public"
    installed(old_apps, b"export const version=1;")
    old = build_public_manifest(old_apps, old_store)
    # Only manifest-selected public code may cross the previous-image boundary.
    (old_store / old["generation"] / "wordcraft/private.json").write_bytes(b"not code")
    installed(settings.apps_dir, b"export const version=2;")
    fresh_store = tmp_path / "fresh-image-public"
    current = build_public_manifest(settings.apps_dir, fresh_store, previous=old_store)
    configured = replace(settings, public_assets_dir=fresh_store)
    assert (old_store / "current").read_text().strip() == old["generation"]
    assert (fresh_store / "current").read_text().strip() == current["generation"]
    assert not (fresh_store / old["generation"] / "wordcraft/private.json").exists()
    assert old["generation"] != current["generation"]
    with TestClient(create_public_app(configured), base_url=settings.origin) as client:
        for origin in (
            settings.origin,
            settings.editor_origin,
            settings.demo_editor_origin,
        ):
            for generation, content in [
                (old["generation"], b"export const version=1;"),
                (current["generation"], b"export const version=2;"),
            ]:
                response = client.get(
                    f"{origin}/public-assets/{generation}/wordcraft/{JS}",
                    headers={"Accept-Encoding": "identity"},
                )
                assert response.status_code == 200 and response.content == content
                assert (
                    response.headers["cache-control"]
                    == "public, max-age=31536000, immutable"
                )
            assert (
                client.get(
                    f"{origin}/public-assets/{'f' * 64}/wordcraft/{JS}"
                ).status_code
                == 404
            )
    assert set(load_public_generations(fresh_store)["generations"]) == {
        old["generation"],
        current["generation"],
    }


@pytest.mark.parametrize(
    "failure",
    [
        "bytes",
        "manifest",
        "file-link",
        "root-link",
        "missing-current",
        "unexpected-root-entry",
    ],
)
def test_upgrade_rejects_invalid_previous_code_before_publication(tmp_path, failure):
    old_apps, old_store = tmp_path / "old-apps", tmp_path / "old-public"
    installed(old_apps)
    old = build_public_manifest(old_apps, old_store)
    asset = old_store / old["generation"] / "wordcraft" / JS
    if failure == "bytes":
        asset.write_bytes(b"tampered")
    elif failure == "manifest":
        (asset.parent.parent / "manifest.json").write_text("{}")
    elif failure == "file-link":
        original = tmp_path / "linked.js"
        original.write_bytes(asset.read_bytes())
        asset.unlink()
        asset.symlink_to(original)
    elif failure == "root-link":
        alias = tmp_path / "alias"
        alias.symlink_to(old_store, target_is_directory=True)
        old_store = alias
    elif failure == "missing-current":
        (old_store / "current").unlink()
    else:
        (old_store / "private-configuration.json").write_text("{}")
    fresh_apps, fresh_store = tmp_path / "new-apps", tmp_path / "new-public"
    installed(fresh_apps, b"export const version=2;")
    with pytest.raises(ValueError):
        build_public_manifest(fresh_apps, fresh_store, previous=old_store)
    assert not (fresh_store / "current").exists()


def test_empty_previous_image_is_supported_for_a_first_installation(tmp_path):
    apps, previous, output = (
        tmp_path / "apps",
        tmp_path / "previous",
        tmp_path / "output",
    )
    installed(apps)
    previous.mkdir()
    current = build_public_manifest(apps, output, previous=previous)
    assert set(load_public_generations(output)["generations"]) == {
        current["generation"]
    }


def test_retention_never_uses_its_input_as_the_new_image_output(tmp_path):
    apps, store = tmp_path / "apps", tmp_path / "store"
    installed(apps)
    old = build_public_manifest(apps, store)
    installed(apps, b"export const version=2;")
    with pytest.raises(ValueError):
        build_public_manifest(apps, store, previous=store)
    assert (store / "current").read_text().strip() == old["generation"]
