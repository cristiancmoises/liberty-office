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
