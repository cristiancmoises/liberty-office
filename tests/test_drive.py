from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from contextlib import closing
from conftest import bootstrap,csrf,invite,activate,ORIGIN

def upload(c,name='test.txt',content=b'hello',parent=None):
    params={'name':name}
    if parent: params['parent']=parent
    return c.post('/api/files',params=params,content=content,headers={**csrf(c),'Content-Type':'application/octet-stream'})

def test_private_files_folders_and_safe_names(env):
    app,c,s=env;bootstrap(c,s)
    r=c.post('/api/folders',json={'name':'Projetos'},headers=csrf(c))
    assert r.status_code==200,r.text
    folder=r.json()['id']
    result=upload(c,'ação <script>.txt',b'private',folder)
    assert result.status_code==200,result.text
    item=result.json()
    download=c.get('/api/files/'+item['id']+'/content')
    assert download.content==b'private'
    assert 'attachment;' in download.headers['content-disposition']
    assert upload(c,'../escape.txt').status_code==422
    assert upload(c,'a\r\nX-Evil: a').status_code==422
    assert upload(c,'ação <script>.txt',parent=folder).status_code==409
    invitation=invite(c)
    with closing(TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN})) as other:
        activate(other,invitation['token'])
        assert other.get('/api/files/'+item['id']+'/content').status_code==404
        assert other.get('/api/files',params={'parent':folder}).status_code==404
        assert other.patch('/api/files/'+item['id'],json={'name':'stolen'},headers=csrf(other)).status_code==404
        assert other.get('/api/files').json()['files']==[]

def test_versions_etag_trash_restore_and_purge_count_quota(env):
    app,c,s=env;bootstrap(c,s)
    item=upload(c).json();file_id=item['id']
    path='/api/files/'+file_id+'/content'
    assert c.put(path,content=b'changed',headers=csrf(c)).status_code==428
    updated=c.put(path,content=b'changed',headers={**csrf(c),'If-Match':item['etag']})
    assert updated.status_code==200,updated.text
    assert c.put(path,content=b'lost',headers={**csrf(c),'If-Match':item['etag']}).status_code==412
    versions=c.get('/api/files/'+file_id+'/versions').json()['versions']
    assert len(versions)==2
    assert c.get(path,params={'version':versions[-1]['id']}).content==b'hello'
    before=c.get('/api/storage').json()['used']
    assert before==12
    assert c.delete('/api/files/'+file_id,headers=csrf(c)).status_code==200
    assert c.get('/api/files').json()['files']==[]
    assert c.get('/api/storage').json()['used']==before
    assert c.get('/api/files',params={'view':'trash'}).json()['files'][0]['id']==file_id
    assert c.post('/api/files/'+file_id+'/restore',headers=csrf(c)).status_code==200
    assert c.delete('/api/files/'+file_id,headers=csrf(c)).status_code==200
    assert c.delete('/api/files/'+file_id+'/purge',headers=csrf(c)).status_code==200
    assert c.get('/api/storage').json()['used']==0
    assert list((s.data_dir/'blobs').iterdir())==[]

def test_quota_limits_and_reservations_are_atomic(env):
    app,c,s=env;bootstrap(c,s)
    invited=invite(c,quota=10)
    with closing(TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN})) as other:
        activate(other,invited['token'])
        headers=csrf(other)
        def send(n):
            return other.post('/api/files',params={'name':str(n)+'.txt'},content=b'123456',headers=headers).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=sorted(pool.map(send,[1,2]))
        assert results==[200,413],results
        assert other.get('/api/storage').json()['used']==6
        assert other.get('/api/storage').json()['reserved']==0
        assert upload(other,'large',b'x'*11).status_code==413
        assert other.get('/api/storage').json()['reserved']==0

def test_internal_readonly_shares_revocation_and_folder_cycle(env):
    app,c,s=env;bootstrap(c,s)
    item=upload(c).json();invited=invite(c)
    root=c.post('/api/folders',json={'name':'root'},headers=csrf(c)).json()['id']
    child=c.post('/api/folders',json={'name':'child','parent':root},headers=csrf(c)).json()['id']
    assert c.patch('/api/files/'+root,json={'parent':child},headers=csrf(c)).status_code==409
    assert c.post('/api/files/'+item['id']+'/shares',json={'username':'alice'},headers=csrf(c)).status_code==200
    with closing(TestClient(app,base_url=ORIGIN,headers={'Origin':ORIGIN})) as other:
        activate(other,invited['token'])
        assert other.get('/api/files',params={'view':'shared'}).json()['files'][0]['id']==item['id']
        assert other.get('/api/files/'+item['id']+'/content').content==b'hello'
        assert other.put('/api/files/'+item['id']+'/content',content=b'no',headers={**csrf(other),'If-Match':item['etag']}).status_code==404
        assert c.delete('/api/files/'+item['id']+'/shares/'+invited['user']['id'],headers=csrf(c)).status_code==200
        assert other.get('/api/files/'+item['id']+'/content').status_code==404

def test_length_mismatch_releases_reservation(env):
    app,c,s=env;bootstrap(c,s)
    r=c.post('/api/files',params={'name':'bad.txt'},content=b'abc',headers={**csrf(c),'Content-Length':'4'})
    assert r.status_code==400
    assert c.get('/api/storage').json()['reserved']==0
    assert c.get('/api/storage').json()['used']==0
    assert list((s.data_dir/'tmp').iterdir())==[]

def test_recent_files_include_nested_files(env):
    app,c,s=env;bootstrap(c,s)
    folder=c.post('/api/folders',json={'name':'Nested'},headers=csrf(c)).json()['id']
    f=upload(c,'nested.txt',parent=folder).json()
    assert c.get('/api/files',params={'view':'recent'}).json()['files'][0]['id']==f['id']
