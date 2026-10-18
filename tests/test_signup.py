"""Public account policy, real MFA gates and concurrent capacity admission."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from threading import Barrier

import pyotp
import pytest
from conftest import ORIGIN, PASSWORD, csrf
from fastapi.testclient import TestClient
from starlette.requests import Request


def body(username="visitor"):
    return {"username": username, "name": "Visitor", "password": PASSWORD}


def anonymous(app, peer="198.51.100.7"):
    return TestClient(
        app, base_url=ORIGIN, headers={"Origin": ORIGIN}, client=(peer, 1234)
    )


def test_signup_disabled_and_empty_bootstrap_cannot_be_taken_over(env):
    app, client, settings = env
    assert client.post("/api/auth/signup", json=body()).status_code == 503
    app.state.svc.settings = replace(settings, public_signup=True)
    assert client.post("/api/auth/signup", json=body()).status_code == 503
    with app.state.svc.db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_signup_fixed_quota_role_and_mandatory_mfa(public_env):
    app, _, _ = public_env
    with closing(anonymous(app)) as client:
        result = client.post("/api/auth/signup", json=body("Visitor"))
        assert result.status_code == 201, result.text
        assert result.json()["state"] == "enroll"
        assert result.json()["csrf"] == client.get("/api/auth/status").json()["csrf"]
        assert "HttpOnly" in result.headers["set-cookie"]
        assert "SameSite=strict" in result.headers["set-cookie"]
        assert client.get("/api/files").status_code == 403
        assert client.get("/api/admin/users").status_code == 403
        setup = client.get("/api/auth/mfa/setup").json()
        verified = client.post(
            "/api/auth/mfa/verify",
            json={"code": pyotp.TOTP(setup["secret"]).now()},
            headers=csrf(client),
        )
        assert verified.status_code == 200
        assert len(verified.json()["recovery_codes"]) == 10
        user = client.get("/api/auth/status").json()["user"]
        assert user["quota"] == 100_000_000 and user["role"] == "user"
        assert client.get("/api/files").status_code == 200
        assert client.get("/api/admin/users").status_code == 403
    with app.state.svc.db.connect() as c:
        row = c.execute(
            "SELECT * FROM public_accounts WHERE user_id=?", (user["id"],)
        ).fetchone()
        assert row["established_at"] is not None
        assert (
            c.execute("SELECT quota FROM users WHERE username='admin'").fetchone()[0]
            == 65536
        )


def fast_hash(monkeypatch, app):
    with app.state.svc.db.connect() as c:
        stored = c.execute(
            "SELECT password FROM users WHERE username='admin'"
        ).fetchone()[0]
    monkeypatch.setattr("liberty.signup.hash_password", lambda _: stored)


def test_invalid_body_and_privilege_injection_are_rejected_before_hash(
    public_env, monkeypatch
):
    app, _, _ = public_env
    calls = []
    monkeypatch.setattr(
        "liberty.signup.hash_password", lambda value: calls.append(value)
    )
    with closing(anonymous(app)) as client:
        for extra in (
            {"role": "admin"},
            {"quota": 2**50},
            {"enabled": True},
            {"totp_confirmed": True},
        ):
            assert (
                client.post("/api/auth/signup", json=body() | extra).status_code == 422
            )
        for password in ("x" * 13, "x" * 257):
            result = client.post(
                "/api/auth/signup", json=body() | {"password": password}
            )
            assert result.status_code == 422 and password not in result.text
        assert client.post("/api/auth/signup", content=b"x" * 16385).status_code == 413
        assert (
            client.post(
                "/api/auth/signup",
                json=body(),
                headers={"Origin": "https://foreign.invalid"},
            ).status_code
            == 403
        )
    assert calls == []


def test_source_attempts_persist_including_failures_and_expire_at_boundary(
    public_env, monkeypatch
):
    from liberty import security, signup

    app, _, _ = public_env
    fast_hash(monkeypatch, app)
    clock = [2_000_000_000]
    monkeypatch.setattr(security, "now", lambda: clock[0])
    monkeypatch.setattr(signup, "now", lambda: clock[0])
    with closing(anonymous(app)) as client:
        assert client.post("/api/auth/signup", json=body()).status_code == 201
        for _ in range(4):
            assert client.post("/api/auth/signup", json=body()).status_code == 409
    with closing(anonymous(app)) as client:
        result = client.post("/api/auth/signup", json=body("another"))
        assert result.status_code == 429 and int(result.headers["retry-after"]) == 3600
        clock[0] += 3599
        assert client.post("/api/auth/signup", json=body("another")).status_code == 429
        clock[0] += 1
        assert client.post("/api/auth/signup", json=body("another")).status_code == 201


@pytest.mark.parametrize("bound", ["slot", "success", "duplicate"])
def test_parallel_last_slot_duplicate_and_success_limit(public_env, monkeypatch, bound):
    app, _, settings = public_env
    fast_hash(monkeypatch, app)
    app.state.svc.settings = replace(
        settings,
        signup_slots=1 if bound == "slot" else 400,
        signup_successes=1 if bound == "success" else 20,
    )
    barrier = Barrier(2)

    def submit(index):
        with closing(anonymous(app, f"198.51.100.{index + 10}")) as client:
            barrier.wait(timeout=10)
            return client.post(
                "/api/auth/signup",
                json=body("duplicate" if bound == "duplicate" else f"visitor{index}"),
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(submit, range(2)))
    assert sorted(results) == [201, 409 if bound == "duplicate" else 429]
    with app.state.svc.db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM public_accounts").fetchone()[0] == 1
        assert (
            c.execute(
                "SELECT count FROM rate_limits WHERE key='signup:success'"
            ).fetchone()[0]
            == 1
        )


def test_twenty_successes_and_four_hundred_slots_are_actual_limits(
    public_env, monkeypatch
):
    app, _, settings = public_env
    fast_hash(monkeypatch, app)
    app.state.svc.settings = replace(settings, signup_attempts=100)
    with closing(anonymous(app)) as client:
        for index in range(20):
            assert (
                client.post("/api/auth/signup", json=body(f"user{index}")).status_code
                == 201
            )
        assert (
            client.post("/api/auth/signup", json=body("twentyfirst")).status_code == 429
        )
    with app.state.svc.db.transaction() as c:
        c.execute("DELETE FROM rate_limits WHERE key='signup:success'")
        sample = c.execute("SELECT * FROM users WHERE username='user0'").fetchone()
        for index in range(20, 399):
            name = f"user{index}"
            c.execute(
                "INSERT INTO users(id,username,name,password,role,quota,totp,created) VALUES(?,?,?,?,?,?,?,?)",
                (
                    name,
                    name,
                    name,
                    sample["password"],
                    "user",
                    100_000_000,
                    sample["totp"],
                    sample["created"],
                ),
            )
            c.execute(
                "INSERT INTO public_accounts(user_id,created_at) VALUES(?,?)",
                (name, sample["created"]),
            )
    with closing(anonymous(app)) as client:
        assert (
            client.post("/api/auth/signup", json=body("fourhundred")).status_code == 201
        )
        assert client.post("/api/auth/signup", json=body("overflow")).status_code == 429


def test_untrusted_forwarded_headers_cannot_rotate_source(public_env, monkeypatch):
    app, _, _ = public_env
    fast_hash(monkeypatch, app)
    with closing(anonymous(app)) as client:
        for index in range(6):
            result = client.post(
                "/api/auth/signup",
                json=body(f"user{index}"),
                headers={
                    "X-Forwarded-For": f"203.0.113.{index + 1}",
                    "X-Real-IP": f"203.0.113.{index + 1}",
                },
            )
            assert result.status_code == (201 if index < 5 else 429)


def test_only_explicit_trusted_proxy_chain_is_used(public_env):
    from liberty.signup import signup_source

    _, _, settings = public_env
    settings = replace(settings, trusted_proxy_cidrs=("192.0.2.0/24",))

    def source(peer, forwarded):
        request = Request(
            {
                "type": "http",
                "client": (peer, 1234),
                "headers": [(b"x-forwarded-for", forwarded.encode())],
            }
        )
        return signup_source(request, settings)

    assert source("192.0.2.10", "203.0.113.4, 192.0.2.11") == "203.0.113.4"
    assert source("192.0.2.10", "198.51.100.1, 203.0.113.4") == "203.0.113.4"
    assert source("198.51.100.7", "203.0.113.4") == "198.51.100.7"
    assert source("192.0.2.10", "not-an-address") == "192.0.2.10"


def test_invitation_default_and_stored_quotas_remain_unchanged(public_env):
    app, operator, settings = public_env
    result = operator.post(
        "/api/admin/users",
        json={"username": "invited", "name": "Invited"},
        headers=csrf(operator),
    )
    assert (
        result.status_code == 200
        and result.json()["user"]["quota"] == settings.default_quota
    )
    with app.state.svc.db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM public_accounts").fetchone()[0] == 0


def test_signup_settings_have_explicit_env_wiring_and_reject_invalid_limits(
    monkeypatch,
):
    from liberty.config import Settings

    monkeypatch.setenv("PUBLIC_SIGNUP_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_SIGNUP_QUOTA_BYTES", "100000000")
    for key, value in {
        "SIGNUP_ATTEMPTS": "7",
        "SIGNUP_SUCCESSES": "22",
        "SIGNUP_WINDOW_SECONDS": "1800",
        "SIGNUP_SLOTS": "300",
        "SIGNUP_PENDING_TTL_SECONDS": "43200",
        "TRUSTED_PROXY_CIDRS": "192.0.2.0/24,2001:db8::/32",
    }.items():
        monkeypatch.setenv(key, value)
    settings = Settings.from_env()
    assert settings.public_signup and settings.signup_quota == 100_000_000
    assert (
        settings.signup_attempts,
        settings.signup_successes,
        settings.signup_window,
        settings.signup_slots,
        settings.signup_pending_ttl,
    ) == (7, 22, 1800, 300, 43200)
    assert settings.trusted_proxy_cidrs == ("192.0.2.0/24", "2001:db8::/32")
    for changes in (
        {"signup_slots": 0},
        {"signup_quota": 0},
        {"signup_attempts": True},
        {"signup_window": 2**63},
        {"trusted_proxy_cidrs": ("192.0.2.7/24",)},
        {"public_signup": "false"},
    ):
        with pytest.raises(ValueError):
            replace(settings, **changes)
    monkeypatch.setenv("PUBLIC_SIGNUP_ENABLED", "maybe")
    with pytest.raises(ValueError):
        Settings.from_env()
