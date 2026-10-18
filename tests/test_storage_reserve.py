"""Catch floor off-by-one, missing global reservations and gated downloads."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest
from conftest import bootstrap, csrf
from fastapi import HTTPException

from liberty.config import Settings
from liberty.drive import reserve


def disk_free(monkeypatch, amount):
    monkeypatch.setattr(
        "liberty.drive.shutil.disk_usage",
        lambda _: SimpleNamespace(total=2**40, used=2**40 - amount, free=amount),
    )


@pytest.mark.parametrize("floor", [None, 1073741824])
@pytest.mark.parametrize(("delta", "status"), [(-1, 507), (0, 200)])
def test_incoming_file_respects_exact_physical_floor(
    env, monkeypatch, floor, delta, status
):
    app, client, settings = env
    bootstrap(client, settings)
    expected = 16777216 if floor is None else floor
    if floor is not None:
        app.state.svc.settings = replace(settings, min_free_bytes=floor)
    disk_free(monkeypatch, expected + 5 + delta)
    result = client.post(
        "/api/files",
        params={"name": "boundary.txt"},
        content=b"12345",
        headers=csrf(client),
    )
    assert result.status_code == status, result.text
    assert client.get("/api/storage").json()["reserved"] == 0
    assert client.get("/api/storage").json()["used"] == (5 if status == 200 else 0)


def test_env_floor_is_used_without_changing_existing_quota_defaults(env, monkeypatch):
    app, client, settings = env
    bootstrap(client, settings)
    monkeypatch.setenv("MIN_FREE_BYTES", "1073741824")
    configured = Settings.from_env()
    assert configured.global_quota == 53687091200
    assert configured.default_quota == 5368709120
    assert configured.max_upload == 104857600
    app.state.svc.settings = replace(settings, min_free_bytes=configured.min_free_bytes)
    disk_free(monkeypatch, 1073741828)
    response = client.post(
        "/api/files",
        params={"name": "blocked.txt"},
        content=b"12345",
        headers=csrf(client),
    )
    assert response.status_code == 507


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "invalid", "1152921504606846977"])
def test_invalid_env_floor_fails_closed(monkeypatch, value):
    monkeypatch.setenv("MIN_FREE_BYTES", value)
    with pytest.raises(ValueError):
        Settings.from_env()


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "16777216", 2**60 + 1])
def test_invalid_programmatic_floor_fails_closed(value):
    with pytest.raises(ValueError):
        Settings(min_free_bytes=value)


def test_parallel_reservations_cannot_spend_the_same_physical_headroom(
    env, monkeypatch
):
    app, client, settings = env
    bootstrap(client, settings)
    service = app.state.svc
    service.settings = replace(settings, min_free_bytes=1073741824)
    disk_free(monkeypatch, 1073741834)
    with service.db.connect() as connection:
        session = dict(
            connection.execute("SELECT * FROM sessions WHERE stage='full'").fetchone()
        )

    def allocate(_):
        try:
            reserve(service, session, 6)
            return 200
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(allocate, (1, 2))) == [200, 507]
    with service.db.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*),SUM(size) FROM reservations"
        ).fetchone()[:] == (1, 6)


def test_other_owners_pending_bytes_are_included(env, monkeypatch):
    app, client, settings = env
    bootstrap(client, settings)
    service = app.state.svc
    service.settings = replace(settings, min_free_bytes=1073741824)
    with service.db.transaction() as connection:
        connection.execute(
            "INSERT INTO users SELECT 'other','other','Other',password,'user',quota,enabled,totp,totp_confirmed,totp_step,created FROM users LIMIT 1"
        )
        connection.execute(
            "INSERT INTO reservations VALUES('other-pending','other',6,1)"
        )
        session = dict(
            connection.execute("SELECT * FROM sessions WHERE stage='full'").fetchone()
        )
    disk_free(monkeypatch, 1073741834)
    with pytest.raises(HTTPException) as error:
        reserve(service, session, 5)
    assert error.value.status_code == 507


def test_downloads_remain_available_at_full_quota_and_zero_free_space(env, monkeypatch):
    app, client, settings = env
    bootstrap(client, settings)
    item = client.post(
        "/api/files",
        params={"name": "keep.txt"},
        content=b"12345",
        headers=csrf(client),
    ).json()
    with app.state.svc.db.transaction() as connection:
        connection.execute("UPDATE users SET quota=5")
    app.state.svc.settings = replace(
        settings, global_quota=5, min_free_bytes=1073741824
    )
    disk_free(monkeypatch, 0)
    response = client.get("/api/files/" + item["id"] + "/content")
    assert response.status_code == 200 and response.content == b"12345"
    assert (
        client.post(
            "/api/files", params={"name": "no.txt"}, content=b"x", headers=csrf(client)
        ).status_code
        == 413
    )


def test_restore_revision_uses_the_same_floor_and_releases_rejected_reservations(
    env, monkeypatch
):
    app, client, settings = env
    bootstrap(client, settings)
    first = client.post(
        "/api/files",
        params={"name": "history.txt"},
        content=b"old",
        headers=csrf(client),
    ).json()
    current = client.put(
        "/api/files/" + first["id"] + "/content",
        content=b"new",
        headers={**csrf(client), "If-Match": first["etag"]},
    ).json()
    app.state.svc.settings = replace(settings, min_free_bytes=1073741824)
    path = "/api/files/" + first["id"] + "/versions/" + first["version"] + "/restore"
    disk_free(monkeypatch, 1073741826)
    assert (
        client.post(
            path, headers={**csrf(client), "If-Match": current["etag"]}
        ).status_code
        == 507
    )
    assert client.get("/api/storage").json()["reserved"] == 0
    assert client.get("/api/files/" + first["id"] + "/content").content == b"new"
    disk_free(monkeypatch, 1073741827)
    assert (
        client.post(
            path, headers={**csrf(client), "If-Match": current["etag"]}
        ).status_code
        == 200
    )
    assert client.get("/api/files/" + first["id"] + "/content").content == b"old"
