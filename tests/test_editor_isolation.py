import json
from urllib.parse import urlsplit
from conftest import bootstrap,csrf

def install(s):
    p=s.apps_dir/'wordcraft';p.mkdir(parents=True)
    (p/'index.html').write_text('<!doctype html><html><head><title>WordCraft</title></head><body><canvas></canvas></body></html>')
    (p/'main.wasm').write_bytes(b'\x00asm')
    (p/'main.js').write_text('export {};')

def launch(c,s):
    install(s);r=c.post('/api/editors/wordcraft',headers=csrf(c));assert r.status_code==200,r.text
    return r.json()

def test_editor_origin_has_no_portal_or_account_apis(env):
    app,c,s=env;bootstrap(c,s)
    assert s.editor_origin!=s.origin
    assert c.get(s.editor_origin+'/api/auth/status').status_code==404
    assert c.get(s.editor_origin+'/').status_code==404
    assert c.post(s.editor_origin+'/api/admin/users',json={'username':'evil','name':'Evil'},headers=csrf(c)).status_code==404
    assert c.get('/api/auth/status').json()['state']=='full'

def test_ticket_serves_only_one_app_and_is_not_a_portal_credential(env):
    app,c,s=env;bootstrap(c,s);item=launch(c,s)
    assert item['origin']==s.editor_origin
    html=c.get(item['url']);assert html.status_code==200,html.text
    assert '__liberty-config' in html.text and 'editor-host.mjs' in html.text
    assert 'csrf' not in html.text and 'liberty_session' not in html.text
    assert "frame-ancestors "+s.origin in html.headers['content-security-policy']
    assert 'x-frame-options' not in html.headers
    base=item['url'].rsplit('/',1)[0]
    wasm=c.get(base+'/main.wasm');assert wasm.content==b'\x00asm' and wasm.headers['content-type']=='application/wasm'
    assert c.get(base+'/%2e%2e%2f..%2fmfa.key').status_code==404
    assert c.get(item['url'].replace(s.editor_origin,s.origin)).status_code==404
    token=urlsplit(item['url']).path.split('/')[2]
    with app.state.svc.db.connect() as db:
        assert db.execute('SELECT id FROM editor_tickets').fetchone()[0]!=token
    assert c.delete('/api/editors/'+item['ticket_id'],headers=csrf(c)).status_code==200
    assert c.get(item['url']).status_code==401

def test_ticket_expires_with_session_and_requires_mfa(env):
    app,c,s=env;bootstrap(c,s);item=launch(c,s)
    with app.state.svc.db.transaction() as db:db.execute('UPDATE sessions SET expires=0')
    assert c.get(item['url']).status_code==401
    assert c.post('/api/editors/wordcraft',headers={'X-CSRF-Token':'bad'}).status_code in (401,403)

def test_ticket_revoked_by_logout(env):
    app,c,s=env;bootstrap(c,s);item=launch(c,s)
    assert c.post('/api/auth/logout',headers=csrf(c)).status_code==200
    assert c.get(item['url']).status_code==401
