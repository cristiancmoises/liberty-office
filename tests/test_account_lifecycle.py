from contextlib import closing
import pyotp
from fastapi.testclient import TestClient
from conftest import bootstrap,invite,activate,csrf,ORIGIN,PASSWORD

def other(app):return closing(TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN}))

def test_reissued_invite_revokes_old_invite(env):
    app,c,s=env;bootstrap(c,s);item=invite(c)
    r=c.post('/api/admin/users/'+item['user']['id']+'/invite',headers=csrf(c))
    assert r.status_code==200,r.text
    with other(app) as user:
        assert user.post('/api/auth/activate',json={'token':item['token'],'password':PASSWORD}).status_code==401
        activate(user,r.json()['token'])
        assert c.post('/api/admin/users/'+item['user']['id']+'/invite',headers=csrf(c)).status_code==409

def test_password_reset_single_use_preserves_mfa_and_revokes_sessions(env):
    app,c,s=env;bootstrap(c,s);item=invite(c)
    with other(app) as user:
        secret,codes=activate(user,item['token'])
        r=c.post('/api/admin/users/'+item['user']['id']+'/password-reset',headers=csrf(c))
        assert r.status_code==200,r.text
        assert user.get('/api/auth/status').json()['state']=='anonymous'
        new_password='Changed-password-very-long-2026!'
        r2=user.post('/api/auth/password-reset',json={'token':r.json()['token'],'password':new_password})
        assert r2.status_code==200,r2.text
        assert r2.json()['state']=='mfa'
        assert user.get('/api/files').status_code==403
        assert user.get('/api/auth/mfa/setup').status_code==403
        assert user.post('/api/auth/password-reset',json={'token':r.json()['token'],'password':PASSWORD}).status_code==401
        assert user.post('/api/auth/mfa/verify',json={'code':codes[0]},headers=csrf(user)).json()['state']=='enroll'

def test_session_list_and_revocation_are_private(env):
    app,c,s=env;bootstrap(c,s);item=invite(c)
    with other(app) as user:
        activate(user,item['token'])
        mine=c.get('/api/auth/sessions');assert mine.status_code==200,mine.text
        current=mine.json()['sessions'][0];assert current['current']
        assert user.delete('/api/auth/sessions/'+current['id'],headers=csrf(user)).status_code==404
        own=user.get('/api/auth/sessions').json()['sessions'][0]
        assert user.delete('/api/auth/sessions/'+own['id'],headers=csrf(user)).status_code==200
        assert user.get('/api/auth/status').json()['state']=='anonymous'

def test_reset_incomplete_enrollment_replaces_secret_and_keeps_mfa_mandatory(env):
    app,c,s=env;bootstrap(c,s);item=invite(c)
    with other(app) as user:
        assert user.post('/api/auth/activate',json={'token':item['token'],'password':PASSWORD}).json()['state']=='enroll'
        before=user.get('/api/auth/mfa/setup').json()['secret']
        reset=c.post('/api/admin/users/'+item['user']['id']+'/password-reset',headers=csrf(c))
        assert reset.status_code==200,reset.text
        assert user.get('/api/auth/status').json()['state']=='anonymous'
        r=user.post('/api/auth/password-reset',json={'token':reset.json()['token'],'password':'Replacement-password-2026-long!'})
        assert r.status_code==200,r.text
        assert r.json()['state']=='enroll'
        assert user.get('/api/files').status_code==403
        after=user.get('/api/auth/mfa/setup').json()['secret'];assert after!=before
        assert user.post('/api/auth/password-reset',json={'token':reset.json()['token'],'password':PASSWORD}).status_code==401
        verified=user.post('/api/auth/mfa/verify',json={'code':pyotp.TOTP(after).now()},headers=csrf(user))
        assert verified.json()['state']=='full'

def test_transaction_authorization_rejects_revoked_snapshot(env):
    from liberty import security
    from fastapi import HTTPException
    import pytest
    app,c,s=env;bootstrap(c,s)
    service=app.state.svc
    with service.db.transaction() as db:
        row=dict(db.execute("SELECT s.*,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.stage='full'").fetchone())
        db.execute('DELETE FROM sessions WHERE id=?',(row['id'],))
        with pytest.raises(HTTPException) as caught:security.authorize(db,row,administrator=True)
        assert caught.value.status_code==401
