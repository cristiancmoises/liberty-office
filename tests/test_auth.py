import pyotp
from fastapi.testclient import TestClient
from contextlib import closing
from conftest import bootstrap,csrf,invite,activate,ORIGIN,PASSWORD

def test_mfa_is_a_hard_gate_and_bootstrap_is_single_use(env):
    app,c,s=env
    token=(s.data_dir/'bootstrap-token').read_text().strip()
    assert c.get('/api/files').status_code==401
    r=c.post('/api/auth/bootstrap',json={'token':token,'username':'admin','name':'Admin','password':PASSWORD})
    assert r.status_code==200
    assert c.get('/api/files').status_code==403
    assert c.get('/api/admin/users').status_code==403
    assert c.get('/apps/wordcraft/index.html').status_code==403
    assert c.post('/api/auth/bootstrap',json={'token':token,'username':'evil','name':'Evil','password':PASSWORD}).status_code==409
    secret=c.get('/api/auth/mfa/setup').json()['secret']
    assert c.post('/api/auth/mfa/verify',json={'code':'000000'},headers=csrf(c)).status_code==401
    r=c.post('/api/auth/mfa/verify',json={'code':pyotp.TOTP(secret).now()},headers=csrf(c))
    assert r.status_code==200 and len(r.json()['recovery_codes'])==10
    assert c.get('/api/auth/status').json()['state']=='full'
    assert c.get('/api/auth/mfa/setup').status_code==403
    assert not (s.data_dir/'bootstrap-token').exists()

def test_origin_csrf_cookie_and_password_validation(env):
    app,c,s=env
    assert c.post('/api/auth/login',json={'username':'x','password':'x'},headers={'Origin':'https://evil.invalid'}).status_code==403
    secret,codes=bootstrap(c,s)
    assert c.post('/api/auth/logout').status_code==403
    cookie=c.cookies.get('liberty_session')
    assert len(cookie)>30
    r=c.post('/api/auth/password',json={'current_password':PASSWORD,'password':'short'},headers=csrf(c))
    assert r.status_code==422
    assert c.post('/api/auth/logout',headers=csrf(c)).status_code==200
    assert c.get('/api/auth/status').json()['state']=='anonymous'

def test_totp_replay_recovery_enrollment_and_invite_single_use(env):
    app,c,s=env
    bootstrap(c,s)
    item=invite(c)
    with closing(TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN})) as other:
        secret,codes=activate(other,item['token'])
        with app.state.svc.db.connect() as db:
            enrolled_step=db.execute('SELECT totp_step FROM users WHERE id=?',(item['user']['id'],)).fetchone()[0]
        # Replay the enrolled factor, not .now(), which may already be a new
        # valid factor if password verification crosses a 30-second boundary.
        enrolled_code=pyotp.TOTP(secret).at(enrolled_step*30)
        assert other.post('/api/auth/activate',json={'token':item['token'],'password':PASSWORD}).status_code==401
        other.post('/api/auth/logout',headers=csrf(other))
        assert other.post('/api/auth/login',json={'username':'alice','password':PASSWORD}).json()['state']=='mfa'
        assert other.post('/api/auth/mfa/verify',json={'code':enrolled_code},headers=csrf(other)).status_code==401
        assert other.post('/api/auth/mfa/verify',json={'code':codes[0]},headers=csrf(other)).json()['state']=='enroll'
        assert other.get('/api/files').status_code==403
        setup=other.get('/api/auth/mfa/setup').json()
        assert setup['secret']!=secret
        assert other.post('/api/auth/mfa/verify',json={'code':pyotp.TOTP(setup['secret']).now()},headers=csrf(other)).status_code==200
        assert other.get('/api/auth/status').json()['state']=='full'
        assert other.get('/api/admin/users').status_code==403
        uid=item['user']['id']
        assert c.patch('/api/admin/users/'+uid,json={'enabled':False},headers=csrf(c)).status_code==200
        assert other.get('/api/auth/status').json()['state']=='anonymous'

def test_secrets_encrypted_and_no_last_admin_lockout(env):
    app,c,s=env
    secret,codes=bootstrap(c,s)
    assert secret.encode() not in (s.data_dir/'liberty.db').read_bytes()
    me=c.get('/api/auth/status').json()['user']
    assert c.patch('/api/admin/users/'+me['id'],json={'role':'user'},headers=csrf(c)).status_code==409
    assert c.patch('/api/admin/users/'+me['id'],json={'enabled':False},headers=csrf(c)).status_code==409
    assert c.post('/api/auth/login',json={'username':'admin','password':'wrong'}).status_code==401

def test_password_rate_limit_persists(env):
    app,c,s=env
    for _ in range(10):
        assert c.post('/api/auth/login',json={'username':'missing','password':PASSWORD}).status_code==401
    assert c.post('/api/auth/login',json={'username':'missing','password':PASSWORD}).status_code==429

def test_blocked_ip_cannot_grow_username_rate_limit_rows(env):
    from liberty.security import now
    app,c,s=env
    with app.state.svc.db.transaction() as db:
        db.execute('INSERT INTO rate_limits VALUES(?,?,?)',('ip:testclient',120,now()+300))
    for name in ('unknown-one','unknown-two'):
        assert c.post('/api/auth/login',json={'username':name,'password':PASSWORD}).status_code==429
    with app.state.svc.db.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM rate_limits WHERE key LIKE 'login:%'").fetchone()[0]==0

def test_validation_response_does_not_echo_password_or_token(env):
    app,c,s=env;secret='sensitive-value'
    r=c.post('/api/auth/bootstrap',json={'password':secret,'token':secret,'username':'!','name':'Test'})
    assert r.status_code==422
    assert secret not in r.text

def test_enrollment_revokes_other_pending_sessions_and_hides_confirmed_secret(env):
    app,c,s=env
    token=(s.data_dir/'bootstrap-token').read_text().strip()
    c.post('/api/auth/bootstrap',json={'token':token,'username':'admin','name':'Admin','password':PASSWORD})
    secret=c.get('/api/auth/mfa/setup').json()['secret']
    with closing(TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN})) as other:
        assert other.post('/api/auth/login',json={'username':'admin','password':PASSWORD}).json()['state']=='enroll'
        old_csrf=csrf(other)
        assert c.post('/api/auth/mfa/verify',json={'code':pyotp.TOTP(secret).now()},headers=csrf(c)).status_code==200
        assert other.get('/api/auth/mfa/setup').status_code in (401,403)
        assert other.get('/api/auth/status').json()['state']=='anonymous'
        assert other.post('/api/auth/mfa/verify',json={'code':pyotp.TOTP(secret).now()},headers=old_csrf).status_code in (401,403)
