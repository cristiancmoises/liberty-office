import hashlib,sqlite3
from pathlib import Path
import pyotp,pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from liberty.app import create_app
from liberty.config import Settings
from liberty.security import hash_password,now
from conftest import ORIGIN,PASSWORD,csrf

def test_preview_database_upgrades_preserving_mfa_and_document(tmp_path):
    data=tmp_path/'data';data.mkdir();(data/'blobs').mkdir();key=Fernet.generate_key();(data/'mfa.key').write_bytes(key)
    secret=pyotp.random_base32();blob='a'*32;file='b'*32;user='c'*32;content=b'document from preview'
    (data/'blobs'/blob).write_bytes(content)
    with sqlite3.connect(data/'liberty.db') as c:
        c.executescript((Path(__file__).parent/'fixtures/v1-schema.sql').read_text())
        c.execute('INSERT INTO users(id,username,name,password,role,quota,totp,totp_confirmed,created) VALUES(?,?,?,?,?,?,?,?,?)',
                  (user,'admin','Admin',hash_password(PASSWORD),'admin',65536,Fernet(key).encrypt(secret.encode()).decode(),1,now()))
        c.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,?,?)',(file,user,None,'old.txt','file',None,now(),now()))
        c.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?)',(blob,file,user,len(content),hashlib.sha256(content).hexdigest(),now(),1))
    settings=Settings(data_dir=data,apps_dir=tmp_path/'apps',origin=ORIGIN)
    with TestClient(create_app(settings),base_url=ORIGIN,headers={'Origin':ORIGIN}) as c:
        assert c.post('/api/auth/login',json={'username':'admin','password':PASSWORD}).json()['state']=='mfa'
        assert c.get('/api/files').status_code==403
        assert c.post('/api/auth/mfa/verify',json={'code':pyotp.TOTP(secret).now()},headers=csrf(c)).json()['state']=='full'
        assert c.get('/api/files/'+file+'/content').content==content
        assert c.get('/api/files/'+file+'/versions').json()['versions'][0]['id']==blob
    with sqlite3.connect(data/'liberty.db') as c:assert c.execute('PRAGMA user_version').fetchone()[0]==2
    assert (data/'mfa.key').read_bytes()==key

def test_future_database_is_never_silently_downgraded(tmp_path):
    data=tmp_path/'data';data.mkdir()
    with sqlite3.connect(data/'liberty.db') as c:c.execute('PRAGMA user_version=3')
    with pytest.raises(RuntimeError,match='mais recente'):create_app(Settings(data_dir=data,apps_dir=tmp_path/'apps'))
    with sqlite3.connect(data/'liberty.db') as c:
        assert c.execute('PRAGMA user_version').fetchone()[0]==3
        assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='users'").fetchone()[0]==0

def test_additive_signup_metadata_old_reader_and_repromotion(public_env):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader

    from test_public_account_lifecycle import seed

    from liberty.db import DB
    from liberty.signup import cleanup_pending

    app, _, _ = public_env
    service = app.state.svc
    frozen = Path(__file__).parent/'fixtures/liberty-db-v2.txt'
    # Exact DB implementation from signed source 8c348e2, not a simulated schema.
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == '3ce4bffe724daa8f2f0ca6fd345fe632d9bcfcf56297dffa321e7b762d43435b'
    loader = SourceFileLoader('frozen_liberty_db_v2', str(frozen))
    spec = spec_from_loader(loader.name, loader)
    assert spec is not None
    old_module = module_from_spec(spec)
    loader.exec_module(old_module)
    with service.db.transaction() as c:
        seed(c, 'rollbackuser', now()-172800)
        # Required before handing data to an uninstrumented old writer.
        c.execute('UPDATE public_accounts SET cleanup_protected=1')
        before = [tuple(row) for row in c.execute('PRAGMA table_info(users)')]
    old = old_module.DB(service.db.path)
    with old.transaction() as c:
        assert c.execute('PRAGMA user_version').fetchone()[0] == 2
        assert c.execute("SELECT quota FROM users WHERE id='rollbackuser'").fetchone()[0] == 100_000_000
        # Old MFA confirmation/recovery knows only the original users columns.
        c.execute("UPDATE users SET totp_confirmed=1 WHERE id='rollbackuser'")
        c.execute("UPDATE users SET totp_confirmed=0 WHERE id='rollbackuser'")
        c.execute("INSERT INTO sessions VALUES('old-session','rollbackuser','enroll','old-csrf',?,0)", (now()+600,))
    promoted = DB(service.db.path)
    with promoted.transaction() as c:
        assert c.execute('PRAGMA user_version').fetchone()[0] == 2
        assert [tuple(row) for row in c.execute('PRAGMA table_info(users)')] == before
        assert cleanup_pending(c, service, now()) == 0
        row = c.execute("SELECT * FROM public_accounts WHERE user_id='rollbackuser'").fetchone()
        assert row['established_at'] is None and row['cleanup_protected'] == 1
        assert c.execute("SELECT 1 FROM sessions WHERE id='old-session'").fetchone()
