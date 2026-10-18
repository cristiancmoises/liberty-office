"""Restore an account-only volume without weakening blob validation."""

from pathlib import Path

import pytest
from conftest import ORIGIN, bootstrap
from fastapi.testclient import TestClient

from liberty.app import create_app
from liberty.cli import make_backup, restore_backup
from liberty.config import Settings
from scripts.liberty_storage import offline_snapshot


def empty_volume(tmp_path: Path, enrolled: bool) -> tuple[Settings, str | None]:
    settings = Settings(
        data_dir=tmp_path / "source", apps_dir=tmp_path / "apps", origin=ORIGIN
    )
    cookie = None
    with TestClient(
        create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as client:
        if enrolled:
            bootstrap(client, settings)
            cookie = client.cookies.get("liberty_session")
        assert list((settings.data_dir / "blobs").iterdir()) == []
    return settings, cookie


@pytest.mark.parametrize("preserve", [False, True])
def test_restore_recreates_private_empty_blob_directory(tmp_path, preserve):
    settings, cookie = empty_volume(tmp_path, enrolled=True)
    archive = tmp_path / "backup.tar.gz"
    with archive.open("wb") as stream:
        make_backup(settings.data_dir, stream)
    target = tmp_path / "restored"
    manifest = restore_backup(archive, target, preserve_sessions=preserve)
    assert not any(name.startswith("blobs/") for name in manifest["files"])
    assert (target / "blobs").is_dir()
    assert (target / "blobs").stat().st_mode & 0o777 == 0o700
    assert list((target / "blobs").iterdir()) == []
    assert (target / "mfa.key").read_bytes() == (
        settings.data_dir / "mfa.key"
    ).read_bytes()
    restored = Settings(data_dir=target, apps_dir=settings.apps_dir, origin=ORIGIN)
    with TestClient(
        create_app(restored), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as client:
        assert cookie is not None
        client.cookies.set("liberty_session", cookie)
        assert client.get("/api/auth/status").json()["state"] == (
            "full" if preserve else "anonymous"
        )


@pytest.mark.parametrize("enrolled", [False, True])
def test_offline_snapshot_validates_empty_volume_before_first_write(tmp_path, enrolled):
    settings, cookie = empty_volume(tmp_path, enrolled)
    target = tmp_path / "restored"
    target.mkdir(mode=0o700)
    receipt = offline_snapshot(settings.data_dir, target, tmp_path / "backup.tar.gz")
    assert receipt["verified"]
    assert (target / "blobs").is_dir()
    assert (target / "blobs").stat().st_mode & 0o777 == 0o700
    assert list((target / "blobs").iterdir()) == []
    restored = Settings(data_dir=target, apps_dir=settings.apps_dir, origin=ORIGIN)
    with TestClient(
        create_app(restored), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as client:
        if cookie:
            client.cookies.set("liberty_session", cookie)
        status = client.get("/api/auth/status").json()
        assert status["setup_required"] is not enrolled
        assert status["state"] == ("full" if enrolled else "anonymous")
