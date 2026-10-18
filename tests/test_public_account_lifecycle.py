"""Unfinished public registration must never retire an established account."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier

import pyotp
from conftest import PASSWORD, csrf
from test_signup import anonymous, body, fast_hash

from liberty.security import digest, now
from liberty.signup import cleanup_pending


def seed(
    c,
    name,
    created,
    *,
    public=True,
    confirmed=0,
    established=None,
    protected=0,
    enabled=1,
):
    sample = c.execute(
        "SELECT password,totp FROM users WHERE username='admin'"
    ).fetchone()
    c.execute(
        "INSERT INTO users(id,username,name,password,role,quota,totp,totp_confirmed,enabled,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            name,
            name,
            name,
            sample["password"],
            "user",
            100_000_000,
            sample["totp"],
            confirmed,
            enabled,
            created,
        ),
    )
    if public:
        c.execute(
            "INSERT INTO public_accounts VALUES(?,?,?,?)",
            (name, created, established, protected),
        )


def test_exact_24h_boundary_and_all_protected_account_kinds(public_env):
    app, _, _ = public_env
    service = app.state.svc
    cutoff = now() - 86400
    with service.db.transaction() as c:
        seed(c, "expired", cutoff)
        seed(c, "recent", cutoff + 1)
        seed(c, "established", cutoff, established=cutoff)
        seed(c, "legacyconfirmed", cutoff, confirmed=1)
        seed(c, "protected", cutoff, protected=1)
        seed(c, "disabled", cutoff, enabled=0)
        seed(c, "invitationonly", cutoff, public=False)
        for name in ("files", "reservation", "invited", "shared", "version"):
            seed(c, name, cutoff)
        admin = c.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        c.execute(
            "INSERT INTO entries VALUES('owned',?,NULL,'owned.txt','file',NULL,?,?)",
            ("files", cutoff, cutoff),
        )
        c.execute(
            "INSERT INTO entries VALUES('other',?,NULL,'other.txt','file',NULL,?,?)",
            (admin, cutoff, cutoff),
        )
        c.execute(
            "INSERT INTO versions VALUES('old-version','other','version',0,?,?,1)",
            ("0" * 64, cutoff),
        )
        c.execute(
            "INSERT INTO reservations VALUES('reserved','reservation',1,?)", (cutoff,)
        )
        c.execute("INSERT INTO invites VALUES('invite','invited',?)", (now() + 600,))
        c.execute("INSERT INTO shares VALUES('other','shared',?)", (cutoff,))
        assert cleanup_pending(c, service, cutoff) == 1
    with service.db.connect() as c:
        assert c.execute("SELECT 1 FROM users WHERE id='expired'").fetchone() is None
        assert c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 12
        assert (
            c.execute(
                "SELECT target FROM audit WHERE action='signup.pending.expire'"
            ).fetchone()[0]
            == "expired"
        )


def test_cleanup_is_bounded_and_disabled_users_keep_their_slot(public_env, monkeypatch):
    from dataclasses import replace

    app, _, settings = public_env
    service = app.state.svc
    cutoff = now() - 86400
    with service.db.transaction() as c:
        for index in range(103):
            seed(c, f"old{index:03}", cutoff)
        assert cleanup_pending(c, service, cutoff) == 100
        assert c.execute("SELECT COUNT(*) FROM public_accounts").fetchone()[0] == 3
        assert cleanup_pending(c, service, cutoff) == 3
        seed(c, "disabled", cutoff, enabled=0)
    fast_hash(monkeypatch, app)
    service.settings = replace(settings, signup_slots=1)
    with closing(anonymous(app)) as client:
        assert client.post("/api/auth/signup", json=body()).status_code == 429


def test_expired_unfinished_username_can_be_registered_again(public_env, monkeypatch):
    app, _, _ = public_env
    fast_hash(monkeypatch, app)
    with app.state.svc.db.transaction() as c:
        seed(c, "visitor", now() - 86400)
    with closing(anonymous(app)) as client:
        result = client.post("/api/auth/signup", json=body())
        assert result.status_code == 201, result.text
        assert result.json()["state"] == "enroll"
    with app.state.svc.db.connect() as c:
        assert (
            c.execute("SELECT id FROM users WHERE username='visitor'").fetchone()[0]
            != "visitor"
        )


def test_establishment_survives_recovery_password_reset_and_cleanup(public_env):
    app, _, _ = public_env
    service = app.state.svc
    with closing(anonymous(app)) as client:
        assert client.post("/api/auth/signup", json=body()).status_code == 201
        setup = client.get("/api/auth/mfa/setup").json()
        result = client.post(
            "/api/auth/mfa/verify",
            json={"code": pyotp.TOTP(setup["secret"]).now()},
            headers=csrf(client),
        )
        assert result.status_code == 200
        recovery = result.json()["recovery_codes"][0]
        user = client.get("/api/auth/status").json()["user"]["id"]
        with service.db.connect() as c:
            established = c.execute(
                "SELECT established_at FROM public_accounts WHERE user_id=?", (user,)
            ).fetchone()[0]
        assert established is not None
        assert client.post("/api/auth/logout", headers=csrf(client)).status_code == 200
        assert (
            client.post(
                "/api/auth/login", json={"username": "visitor", "password": PASSWORD}
            ).json()["state"]
            == "mfa"
        )
        assert (
            client.post(
                "/api/auth/mfa/verify", json={"code": recovery}, headers=csrf(client)
            ).json()["state"]
            == "enroll"
        )
        reset = "synthetic-password-reset-token-for-test"
        with service.db.transaction() as c:
            c.execute(
                "INSERT INTO password_resets VALUES(?,?,?)",
                (digest(reset), user, now() + 600),
            )
        assert (
            client.post(
                "/api/auth/password-reset",
                json={"token": reset, "password": PASSWORD + "-new"},
            ).status_code
            == 200
        )
    with service.db.transaction() as c:
        assert cleanup_pending(c, service, now() + 172800) == 0
        row = c.execute(
            "SELECT p.established_at,u.totp_confirmed FROM public_accounts p JOIN users u ON u.id=p.user_id WHERE u.id=?",
            (user,),
        ).fetchone()
        assert row["established_at"] == established and row["totp_confirmed"] == 0


def test_mfa_and_cleanup_race_have_only_one_valid_owner(public_env):
    app, _, _ = public_env
    service = app.state.svc
    with closing(anonymous(app)) as client:
        assert client.post("/api/auth/signup", json=body()).status_code == 201
        setup = client.get("/api/auth/mfa/setup").json()
        cutoff = now() - 86400
        with service.db.transaction() as c:
            user = c.execute(
                "SELECT id FROM users WHERE username='visitor'"
            ).fetchone()[0]
            c.execute("UPDATE users SET created=? WHERE id=?", (cutoff, user))
            c.execute(
                "UPDATE public_accounts SET created_at=? WHERE user_id=?",
                (cutoff, user),
            )
        token = csrf(client)
        code = pyotp.TOTP(setup["secret"]).now()
        barrier = Barrier(2)

        def expire():
            barrier.wait(timeout=10)
            with service.db.transaction() as c:
                return cleanup_pending(c, service, cutoff)

        def confirm():
            barrier.wait(timeout=10)
            return client.post(
                "/api/auth/mfa/verify", json={"code": code}, headers=token
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            expired, confirmed = pool.submit(expire), pool.submit(confirm)
            deleted, status = expired.result(timeout=20), confirmed.result(timeout=20)
        assert (deleted, status) in ((0, 200), (1, 401), (1, 403))
        with service.db.connect() as c:
            row = c.execute(
                "SELECT established_at FROM public_accounts WHERE user_id=?", (user,)
            ).fetchone()
            assert (row is None) if deleted else (row["established_at"] is not None)
