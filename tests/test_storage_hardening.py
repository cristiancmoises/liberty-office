from contextlib import closing
from pathlib import Path
import sqlite3,pytest
from fastapi.testclient import TestClient
from liberty.app import create_app
from liberty.config import Settings
from conftest import bootstrap,invite,activate,csrf,ORIGIN
from test_drive import upload

def revisions(c):
    first=upload(c,'history.txt',b'old').json()
    second=c.put('/api/files/'+first['id']+'/content',content=b'new',headers={**csrf(c),'If-Match':first['etag']}).json()
    return first,second

def test_shared_readers_do_not_see_previous_sensitive_versions(env):
    app,c,s=env;bootstrap(c,s);old,current=revisions(c);item=invite(c)
    c.post('/api/files/'+old['id']+'/shares',json={'username':'alice'},headers=csrf(c))
    with closing(TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN})) as user:
        activate(user,item['token'])
        assert user.get('/api/files/'+old['id']+'/content').content==b'new'
        assert user.get('/api/files/'+old['id']+'/versions').status_code==403
        assert user.get('/api/files/'+old['id']+'/content',params={'version':old['version']}).status_code==403

def test_delete_old_revision_reclaims_quota_without_deleting_current(env):
    app,c,s=env;bootstrap(c,s);old,current=revisions(c)
    path='/api/files/'+old['id']+'/versions/'
    assert c.delete(path+current['version'],headers=csrf(c)).status_code==409
    assert c.delete(path+old['version'],headers=csrf(c)).status_code==200
    assert c.get('/api/storage').json()['used']==3
    assert c.get('/api/files/'+old['id']+'/content').content==b'new'

def test_restore_revision_is_new_version_and_requires_current_etag(env):
    app,c,s=env;bootstrap(c,s);old,current=revisions(c)
    path='/api/files/'+old['id']+'/versions/'+old['version']+'/restore'
    assert c.post(path,headers=csrf(c)).status_code==428
    assert c.post(path,headers={**csrf(c),'If-Match':old['etag']}).status_code==412
    r=c.post(path,headers={**csrf(c),'If-Match':current['etag']});assert r.status_code==200,r.text
    assert r.json()['version'] not in (old['version'],current['version'])
    assert c.get('/api/files/'+old['id']+'/content').content==b'old'
    assert c.get('/api/storage').json()['used']==9

def test_json_bodies_limited_before_parsing(env):
    app,c,s=env
    assert c.post('/api/auth/login',content=b'x'*17000,headers={'Content-Type':'application/json'}).status_code==413
    def chunks():yield b'x'*8000;yield b'x'*9000
    assert c.post('/api/auth/login',content=chunks(),headers={'Content-Type':'application/json'}).status_code==413

def test_missing_mfa_key_never_silently_generates_a_replacement(tmp_path):
    s=Settings(data_dir=tmp_path/'data',apps_dir=tmp_path/'apps',origin=ORIGIN)
    with TestClient(create_app(s),base_url=ORIGIN,headers={'Origin':ORIGIN}) as c:bootstrap(c,s)
    (s.data_dir/'mfa.key').unlink()
    with pytest.raises(RuntimeError,match='MFA'):create_app(s)
    assert not (s.data_dir/'mfa.key').exists()

def test_future_database_version_is_rejected(tmp_path):
    from liberty.db import DB
    p=tmp_path/'future.db'
    with sqlite3.connect(p) as c:c.execute('PRAGMA user_version=999')
    with pytest.raises(RuntimeError,match='versão'):DB(p)
