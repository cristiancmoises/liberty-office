import pytest
from liberty.config import Settings


def test_demo_origin_is_separate_from_portal_and_private_editors():
    settings = Settings()
    assert settings.demo_editor_origin == 'http://localhost:8099'
    for origin in (settings.origin, settings.editor_origin):
        with pytest.raises(ValueError):
            Settings(demo_editor_origin=origin)


def test_public_demo_does_not_grant_account_or_drive_access(env):
    app, client, settings = env
    target = settings.apps_dir / 'wordcraft'
    target.mkdir(parents=True)
    (target / 'index.html').write_text('<html><head></head><body><canvas></canvas><script type="module">start()</script></body></html>')
    (target / 'app.wasm').write_bytes(b'\x00asm')
    assert client.get('/demo').status_code == 200
    catalog = client.get('/demo/apps').json()['apps']
    assert len(catalog) == 13
    word = next(item for item in catalog if item['id'] == 'wordcraft')
    assert word['url'].startswith(settings.demo_editor_origin + '/demo/runtime/wordcraft/')
    html = client.get(word['url'])
    assert html.status_code == 200
    assert 'demo-host.mjs' in html.text
    assert 'editor-host.mjs' not in html.text
    assert 'application/x-liberty-module' in html.text
    assert client.get(word['url'].replace('index.html', 'app.wasm')).content == b'\x00asm'
    for path in ('/api/auth/status', '/api/files', '/demo/apps', '/runtime/not-a-ticket/index.html'):
        assert client.get(settings.demo_editor_origin + path).status_code == 404
    assert client.get('/api/files').status_code == 401
    assert client.post('/api/files?name=demo.txt', content=b'no').status_code in (401, 403)
    assert client.post(settings.demo_editor_origin + '/api/files', content=b'no').status_code == 404
    assert client.get(word['url'].replace(settings.demo_editor_origin, settings.editor_origin)).status_code == 404
    assert client.get(word['url'].replace(settings.demo_editor_origin, settings.origin)).status_code == 404
    for path in ('../mfa.key', '%2e%2e%2f../mfa.key', '__liberty/editor-host.mjs'):
        assert client.get(word['url'].replace('index.html', path)).status_code == 404
    with app.state.svc.db.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM editor_tickets').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0


def test_demo_frame_policy_denies_document_import_and_external_connections(env):
    _, client, settings = env
    headers = client.get(settings.demo_editor_origin + '/healthz').headers
    assert 'clipboard-read=()' in headers['permissions-policy']
    assert 'camera=()' in headers['permissions-policy']
    assert 'form-action \'none\'' in headers['content-security-policy']
    assert 'frame-ancestors ' + settings.origin in headers['content-security-policy']
