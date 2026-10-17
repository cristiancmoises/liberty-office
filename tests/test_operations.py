import io,tarfile,json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from liberty.app import create_app
from liberty.config import Settings
from liberty.cli import make_backup,restore_backup
from conftest import bootstrap,csrf,ORIGIN

def test_offline_backup_restore_retains_files_and_mfa(tmp_path):
    s=Settings(data_dir=tmp_path/'data',apps_dir=tmp_path/'apps',origin=ORIGIN)
    app=create_app(s)
    archive=tmp_path/'backup.tar.gz'
    with TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN}) as c:
        secret,codes=bootstrap(c,s)
        item=c.post('/api/files',params={'name':'valuable.txt'},content=b'valuable data',headers=csrf(c)).json()
        with pytest.raises(RuntimeError,match='Pare'):
            with archive.open('wb') as w: make_backup(s.data_dir,w)
    with archive.open('wb') as w:make_backup(s.data_dir,w)
    target=tmp_path/'restored';restore_backup(archive,target)
    assert not (target/'liberty.db-wal').exists()
    assert not (target/'liberty.db-shm').exists()
    with archive.open('rb') as stream:restore_backup(stream,tmp_path/'stream-restored')
    assert (target/'mfa.key').read_bytes()==(s.data_dir/'mfa.key').read_bytes()
    app2=create_app(Settings(data_dir=target,apps_dir=tmp_path/'apps',origin=ORIGIN))
    with TestClient(app2,base_url=ORIGIN,headers={'Origin':ORIGIN}) as c:
        assert c.get('/api/auth/status').json()['state']=='anonymous'
        from conftest import PASSWORD
        c.post('/api/auth/login',json={'username':'admin','password':PASSWORD})
        assert c.post('/api/auth/mfa/verify',json={'code':codes[0]},headers=csrf(c)).json()['state']=='enroll'
        assert (target/'blobs'/item['version']).read_bytes()==b'valuable data'
    with pytest.raises(ValueError,match='vazio'):restore_backup(archive,target)

def test_restore_rejects_traversal_and_corruption(tmp_path):
    p=tmp_path/'evil.tar.gz'
    with tarfile.open(p,'w:gz') as t:
        content=b'x';info=tarfile.TarInfo('../escape');info.size=1;t.addfile(info,io.BytesIO(content))
    with pytest.raises(ValueError):restore_backup(p,tmp_path/'out')
    assert not (tmp_path/'escape').exists()

def test_public_origin_rejects_remote_http():
    with pytest.raises(ValueError):Settings(origin='http://office.example.org')
    with pytest.raises(ValueError):Settings(origin='https://office.example.org/path')
    assert Settings(origin='https://office.example.org').secure

def test_restore_rejects_wrong_mfa_key_even_if_manifest_matches(tmp_path):
    import hashlib
    from cryptography.fernet import Fernet
    settings=Settings(data_dir=tmp_path/'data',apps_dir=tmp_path/'apps',origin=ORIGIN)
    with TestClient(create_app(settings),base_url=ORIGIN,headers={'Origin':ORIGIN}) as c:bootstrap(c,settings)
    archive=tmp_path/'ok.tar.gz'
    with archive.open('wb') as stream:make_backup(settings.data_dir,stream)
    with tarfile.open(archive) as source:files={m.name:source.extractfile(m).read() for m in source.getmembers()}
    files['mfa.key']=Fernet.generate_key();manifest=json.loads(files['BACKUP.json'])
    manifest['files']['mfa.key']={'size':len(files['mfa.key']),'sha256':hashlib.sha256(files['mfa.key']).hexdigest()}
    files['BACKUP.json']=json.dumps(manifest).encode();bad=tmp_path/'bad.tar.gz'
    with tarfile.open(bad,'w:gz') as target:
        for name,data in files.items():info=tarfile.TarInfo(name);info.size=len(data);target.addfile(info,io.BytesIO(data))
    with pytest.raises(ValueError,match='MFA'):restore_backup(bad,tmp_path/'target')

def test_app_cannot_initialize_database_while_backup_holds_volume(tmp_path):
    from liberty.cli import offline
    settings=Settings(data_dir=tmp_path/'data',apps_dir=tmp_path/'apps',origin=ORIGIN)
    with offline(settings.data_dir):
        with pytest.raises(RuntimeError):create_app(settings)
        assert not (settings.data_dir/'liberty.db').exists()
        assert not (settings.data_dir/'blobs').exists()

def test_cli_status_never_initializes_database_and_recover_obeys_lock(tmp_path):
    import os,subprocess,sys
    from liberty.cli import offline
    data=tmp_path/'data';env={**os.environ,'LIBERTY_DATA':str(data),'PUBLIC_ORIGIN':ORIGIN}
    with offline(data):
        for args in (['status'],['recover','admin']):
            result=subprocess.run([sys.executable,'-m','liberty.cli',*args],env=env,capture_output=True,text=True)
            assert result.returncode!=0,result.stdout
            assert not (data/'liberty.db').exists()

def test_operator_can_reset_only_admin_password_without_removing_mfa(tmp_path):
    import os,subprocess,sys
    from urllib.parse import urlsplit,parse_qs
    settings=Settings(data_dir=tmp_path/'data',apps_dir=tmp_path/'apps',origin=ORIGIN)
    with TestClient(create_app(settings),base_url=ORIGIN,headers={'Origin':ORIGIN}) as c:bootstrap(c,settings)
    env={**os.environ,'LIBERTY_DATA':str(settings.data_dir),'PUBLIC_ORIGIN':ORIGIN}
    r=subprocess.run([sys.executable,'-m','liberty.cli','password-reset','admin'],env=env,text=True,capture_output=True)
    assert r.returncode==0,r.stderr
    url=r.stdout.strip().splitlines()[-1];token=parse_qs(urlsplit(url).fragment)['reset'][0]
    with TestClient(create_app(settings),base_url=ORIGIN,headers={'Origin':ORIGIN}) as c:
        r=c.post('/api/auth/password-reset',json={'token':token,'password':'Restored-admin-password-2026!'})
        assert r.status_code==200,r.text
        assert r.json()['state']=='mfa'
        assert c.get('/api/files').status_code==403
        assert c.get('/api/auth/mfa/setup').status_code==403
