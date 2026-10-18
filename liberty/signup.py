"""Bounded free registration; established accounts and their files never expire."""

import sqlite3
from ipaddress import ip_address, ip_network

from fastapi import HTTPException, Request, Response

from .config import Settings
from .models import PublicSignup
from .security import Service, hash_password, now, uid


def signup_source(request: Request, settings: Settings) -> str:
    """Use the rightmost untrusted peer, never an untrusted forwarding header."""
    direct = request.client.host if request.client else "unknown"
    networks = tuple(ip_network(value) for value in settings.trusted_proxy_cidrs)
    try:
        peer = ip_address(direct)
    except ValueError:
        return direct
    if not any(peer in network for network in networks):
        return str(peer)
    raw = ",".join(request.headers.getlist("x-forwarded-for"))
    parts = raw.split(",")
    if len(raw) > 2048 or len(parts) > 32:
        return str(peer)
    try:
        chain = [ip_address(value.strip()) for value in parts]
    except ValueError:
        return str(peer)
    while chain and any(peer in network for network in networks):
        peer = chain.pop()
    return str(peer)


def cleanup_pending(
    c: sqlite3.Connection, service: Service, cutoff: int, limit: int = 100
) -> int:
    """Caller owns BEGIN IMMEDIATE, serializing cleanup with MFA and uploads."""
    if not 1 <= limit <= 100:
        raise ValueError(
            "Pending cleanup is limited to 1–100 accounts per transaction."
        )
    rows = c.execute(
        """SELECT p.user_id FROM public_accounts p JOIN users u ON u.id=p.user_id
        WHERE p.established_at IS NULL AND p.cleanup_protected=0
          AND p.created_at<=? AND u.created<=? AND u.totp_confirmed=0 AND u.enabled=1
          AND NOT EXISTS(SELECT 1 FROM entries WHERE owner=u.id)
          AND NOT EXISTS(SELECT 1 FROM versions WHERE owner=u.id)
          AND NOT EXISTS(SELECT 1 FROM reservations WHERE owner=u.id)
          AND NOT EXISTS(SELECT 1 FROM invites WHERE user_id=u.id)
          AND NOT EXISTS(SELECT 1 FROM shares WHERE recipient=u.id)
        ORDER BY p.created_at,p.user_id LIMIT ?""",
        (cutoff, cutoff, limit),
    ).fetchall()
    for row in rows:
        user_id = row["user_id"]
        service.audit(c, None, "signup.pending.expire", user_id)
        c.execute("DELETE FROM public_accounts WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
    return len(rows)


def signup(
    c: sqlite3.Connection, service: Service, identity: PublicSignup, response: Response
) -> dict:
    """Create ordinary user, capacity counter and enrollment session atomically."""
    cfg = service.settings
    if not cfg.public_signup:
        raise HTTPException(503, "Public registration is not available.")
    if not c.execute(
        "SELECT 1 FROM users WHERE role='admin' AND enabled=1 AND totp_confirmed=1 LIMIT 1"
    ).fetchone():
        raise HTTPException(
            503, "The operator must finish initial setup before registration opens."
        )
    t = now()
    cleanup_pending(c, service, t - cfg.signup_pending_ttl)
    if c.execute(
        "SELECT 1 FROM users WHERE username=?", (identity.username,)
    ).fetchone():
        raise HTTPException(409, "That username is already registered.")
    if (
        c.execute("SELECT COUNT(*) FROM public_accounts").fetchone()[0]
        >= cfg.signup_slots
    ):
        raise HTTPException(
            429,
            "Public account capacity is temporarily full.",
            headers={"Retry-After": str(cfg.signup_window)},
        )
    row = c.execute(
        "SELECT count,reset FROM rate_limits WHERE key='signup:success'"
    ).fetchone()
    count = row["count"] if row and row["reset"] > t else 0
    reset = row["reset"] if row and row["reset"] > t else t + cfg.signup_window
    if count >= cfg.signup_successes:
        raise HTTPException(
            429,
            "Registration is busy. Please try again later.",
            headers={"Retry-After": str(max(1, reset - t))},
        )
    user_id = uid()
    password = hash_password(identity.password)
    c.execute(
        """INSERT INTO users(id,username,name,password,role,quota,totp,created)
        VALUES(?,?,?,?,?,?,?,?)""",
        (
            user_id,
            identity.username,
            identity.name,
            password,
            "user",
            cfg.signup_quota,
            service.new_secret(),
            t,
        ),
    )
    c.execute(
        "INSERT INTO public_accounts(user_id,created_at) VALUES(?,?)", (user_id, t)
    )
    c.execute(
        "INSERT OR REPLACE INTO rate_limits VALUES('signup:success',?,?)",
        (count + 1, reset),
    )
    csrf = service.new_session(c, user_id, "enroll", response)
    service.audit(c, user_id, "signup.create")
    return {"state": "enroll", "csrf": csrf}
