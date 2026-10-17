import io,json,zipfile
from pathlib import Path
import pytest
from conftest import bootstrap
from scripts.fetch_apps import extract_bundle, verify_archive

def archive(entries):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        for name,data in entries.items(): z.writestr(name,data)
    return stream.getvalue()

def test_catalog_and_protected_wasm_mime(env):
    app,c,s=env
    assert c.get('/apps/wordcraft/index.html').status_code==401
    bootstrap(c,s)
    catalog=c.get('/api/apps').json()['apps']
    assert len(catalog)==13
    assert {a['id'] for a in catalog}>={'filmcraft','wordcraft','gridcraft','deckcraft'}
    target=s.apps_dir/'wordcraft';target.mkdir(parents=True)
    (target/'index.html').write_text('<html></html>')
    (target/'test.wasm').write_bytes(b'\x00asm')
    ticket=c.post('/api/editors/wordcraft',headers=__import__('conftest').csrf(c)).json();base=ticket['url'].rsplit('/',1)[0]
    assert c.get(base+'/test.wasm').headers['content-type']=='application/wasm'
    assert '<html></html>' in c.get(ticket['url']).text
    assert c.get('/apps/wordcraft/index.html').status_code==410
    assert c.get('/apps/wordcraft/%2e%2e%2f..%2fmfa.key').status_code==404
    assert c.get('/apps/unknown/index.html').status_code==404

def test_verify_rejects_corrupted_archive(tmp_path):
    p=tmp_path/'bundle.zip';p.write_bytes(b'wrong')
    with pytest.raises(ValueError,match='SHA-256'):verify_archive(p,'0'*64)

@pytest.mark.parametrize('bad',['../escape','/absolute','root/../../escape','C:\\escape','root/link'])
def test_extraction_rejects_zip_slip_and_symlink(tmp_path,bad):
    p=tmp_path/'b.zip'
    with zipfile.ZipFile(p,'w') as z:
        z.writestr('root/index.html','hi')
        if bad=='root/link':
            info=zipfile.ZipInfo(bad);info.create_system=3;info.external_attr=(0o120777<<16);z.writestr(info,'../outside')
        else:z.writestr(bad,'evil')
    with pytest.raises(ValueError):extract_bundle(p,tmp_path/'out')
    assert not (tmp_path/'escape').exists()

def test_extract_preserves_original_bundle_and_notices(tmp_path):
    p=tmp_path/'b.zip';p.write_bytes(archive({'web/index.html':'hi','web/main.js':'export {}','web/LICENSE-MIT':'license'}))
    extract_bundle(p,tmp_path/'out')
    assert (tmp_path/'out/index.html').read_text()=='hi'
    assert (tmp_path/'out/LICENSE-MIT').read_text()=='license'

def test_existing_upstream_gzip_is_preserved(tmp_path):
    import gzip,hashlib
    from scripts.fetch_apps import install
    original=gzip.compress(b'export const a=1',mtime=1)
    data=archive({'web/index.html':'hi','web/main.js':'export const a=1','web/main.js.gz':original,'web/main.wasm':b'\x00asm'})
    cache=tmp_path/'cache';cache.mkdir();(cache/'bundle.zip').write_bytes(data)
    app={'id':'test','name':'Test','version':'v1','url':'https://github.com/test/bundle.zip','sha256':hashlib.sha256(data).hexdigest(),'size':len(data)}
    install(app,tmp_path/'out',cache)
    assert (tmp_path/'out/test/main.js.gz').read_bytes()==original
