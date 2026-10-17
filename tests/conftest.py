from pathlib import Path
import pytest, pyotp
from fastapi.testclient import TestClient
from liberty.app import create_app
from liberty.config import Settings

ORIGIN = 'http://localhost:8097'
PASSWORD = 'Liberty-test-password-42!'

@pytest.fixture
def env(tmp_path):
    settings = Settings(data_dir=tmp_path/'data', apps_dir=tmp_path/'apps', origin=ORIGIN,
                        global_quota=1024*1024, default_quota=65536, max_upload=262144)
    app = create_app(settings)
    with TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN}) as client:
        yield app, client, settings

def csrf(client):
    return {'X-CSRF-Token': client.get('/api/auth/status').json()['csrf']}

def bootstrap(client, settings):
    r = client.post('/api/auth/bootstrap', json={'token': (settings.data_dir/'bootstrap-token').read_text().strip(),
        'username': 'admin', 'name': 'Admin Liberty', 'password': PASSWORD})
    assert r.status_code == 200, r.text
    setup = client.get('/api/auth/mfa/setup').json()
    r = client.post('/api/auth/mfa/verify', json={'code':pyotp.TOTP(setup['secret']).now()}, headers=csrf(client))
    assert r.status_code == 200, r.text
    return setup['secret'], r.json()['recovery_codes']

def invite(client, username='alice', quota=4096, role='user'):
    r=client.post('/api/admin/users',json={'username':username,'name':username.title(),'quota':quota,'role':role},headers=csrf(client))
    assert r.status_code == 200, r.text
    return r.json()

def activate(client, token):
    r=client.post('/api/auth/activate',json={'token':token,'password':PASSWORD})
    assert r.status_code == 200,r.text
    setup=client.get('/api/auth/mfa/setup').json()
    r=client.post('/api/auth/mfa/verify',json={'code':pyotp.TOTP(setup['secret']).now()},headers=csrf(client))
    assert r.status_code == 200,r.text
    return setup['secret'],r.json()['recovery_codes']
