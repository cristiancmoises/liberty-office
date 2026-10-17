import hashlib
import os
import re
import secrets
import time
import threading
import uuid
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request
import pyotp

COOKIE = "liberty_session"
PH = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
PASSWORD_SLOTS = threading.BoundedSemaphore(2)
DUMMY = PH.hash(secrets.token_urlsafe(24))


def hash_password(value):
    with PASSWORD_SLOTS:
        return PH.hash(value)


def now():
    return int(time.time())


def uid():
    return uuid.uuid4().hex


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def check_password(stored, password):
    try:
        with PASSWORD_SLOTS:
            return PH.verify(stored or DUMMY, password)
    except (VerificationError, InvalidHashError):
        return False


def private_file(path: Path, value: bytes):
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, "wb") as f:
        f.write(value)


class Service:
    def __init__(self, settings, db):
        self.settings, self.db = settings, db
        with db.connect() as c:
            users=c.execute('SELECT totp FROM users WHERE totp IS NOT NULL').fetchall()
            empty=c.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0
        key=settings.data_dir/'mfa.key'
        if not empty and not key.is_file():
            raise RuntimeError('Chave MFA ausente. Restaure a chave original do backup; ela não será recriada.')
        private_file(key,Fernet.generate_key())
        try:
            self.crypto=Fernet(key.read_bytes())
            for user in users:self.crypto.decrypt(user['totp'].encode())
        except Exception:
            raise RuntimeError('Chave MFA inválida ou incompatível com o banco. Restaure o backup original.')
        if empty:
            private_file(settings.data_dir/"bootstrap-token", secrets.token_urlsafe(32).encode())

    def new_secret(self):
        return self.crypto.encrypt(pyotp.random_base32().encode()).decode()

    def secret(self, encrypted):
        return self.crypto.decrypt(encrypted.encode()).decode()

    def limit(self, key, maximum=10, window=300):
        t = now()
        with self.db.transaction() as c:
            row = c.execute("SELECT count,reset FROM rate_limits WHERE key=?", (key,)).fetchone()
            count = row['count'] + 1 if row and row['reset'] > t else 1
            reset = row['reset'] if row and row['reset'] > t else t+window
            c.execute("INSERT OR REPLACE INTO rate_limits VALUES(?,?,?)", (key,count,reset))
            c.execute("DELETE FROM rate_limits WHERE reset<?", (t-3600,))
        if count > maximum:
            raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos.", headers={"Retry-After":str(max(1,reset-t))})

    def new_session(self, c, user_id, stage, response):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        seconds = self.settings.session_seconds if stage == 'full' else 600
        c.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?)",
                  (digest(token),user_id,stage,csrf,now()+seconds,now() if stage=='full' else 0))
        c.execute("DELETE FROM sessions WHERE expires<?", (now(),))
        response.set_cookie(COOKIE, token, max_age=seconds, httponly=True,
                            secure=self.settings.secure, samesite='strict', path='/')
        return csrf

    def session(self, request):
        token = request.cookies.get(COOKIE, '')
        if not token:
            return None
        with self.db.connect() as c:
            row = c.execute("""SELECT s.*,u.username,u.name,u.role,u.enabled,u.quota,
                u.totp_confirmed FROM sessions s JOIN users u ON s.user_id=u.id
                WHERE s.id=? AND s.expires>? AND u.enabled=1""", (digest(token),now())).fetchone()
        return dict(row) if row else None

    def audit(self, c, actor, action, target=None):
        c.execute("INSERT INTO audit(actor,action,target,created) VALUES(?,?,?,?)", (actor,action,target,now()))
        # Bounded metadata log; never include passwords, document names or secret values.
        c.execute("DELETE FROM audit WHERE id < (SELECT COALESCE(MAX(id),0)-10000 FROM audit)")


def svc(request: Request):
    return request.app.state.svc


def pending(request: Request):
    session = svc(request).session(request)
    if not session:
        raise HTTPException(401, "Entre na sua conta.")
    return session


def full(request: Request):
    session = pending(request)
    if session['stage'] != 'full' or not session['totp_confirmed']:
        raise HTTPException(403, "Confirme o MFA para continuar.")
    return session


def admin(request: Request):
    session = full(request)
    if session['role'] != 'admin':
        raise HTTPException(403, "Acesso administrativo necessário.")
    return session


def recent(session):
    if now() - session['auth_at'] > 600:
        raise HTTPException(428, "Confirme sua senha e um novo código MFA para esta ação.")


def totp_step(service, user, code):
    if not re.fullmatch(r'\d{6}', code):
        return None
    otp = pyotp.TOTP(service.secret(user['totp']))
    step = now() // 30
    for candidate in (step, step-1, step+1):
        if candidate > user['totp_step'] and secrets.compare_digest(otp.at(candidate*30), code):
            return candidate
    return None


def public_user(row):
    return {k:row[k] for k in ('id','username','name','role','quota','enabled','totp_confirmed')}


def authorize(c, session, administrator=False, fresh=False):
    """Repeat authorization under the write lock, after any dependency snapshot."""
    row=c.execute("""SELECT s.*,u.role,u.enabled,u.totp_confirmed FROM sessions s
        JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.expires>? AND u.enabled=1""",
        (session['id'],now())).fetchone()
    if not row:
        raise HTTPException(401,'Sessão revogada ou expirada.')
    if row['stage']!='full' or not row['totp_confirmed']:
        raise HTTPException(403,'Confirme o MFA antes desta operação.')
    if administrator and row['role']!='admin':
        raise HTTPException(403,'Acesso administrativo necessário.')
    if fresh:
        recent(row)
    return dict(row)
