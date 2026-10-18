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
    assert client.get(word['url'].replace('index.html', '__liberty/demo-session.mjs')).status_code == 200
    assert client.get(word['url'].replace('index.html', '__liberty/demo-policy.mjs')).status_code == 200
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


def test_native_preloads_wait_for_full_mode_without_changing_styles(env):
    from html.parser import HTMLParser

    _, client, settings = env
    target = settings.apps_dir / 'wordcraft'
    target.mkdir(parents=True)
    (target / 'index.html').write_text('''<!doctype html><html><head>
      <link rel="preload" href="./word_bg.wasm" as="fetch" type="application/wasm" crossorigin="anonymous" integrity="sha384-wasm">
      <link rel="modulepreload" href="./word.js" integrity="sha384-module" crossorigin="anonymous">
      <link rel="preload" href="./font.woff2" as="font" type="font/woff2">
      <link rel="stylesheet" href="./editor.css">
      </head><body><script type="module">start()</script></body></html>''')
    response = client.get(settings.demo_editor_origin + '/demo/runtime/wordcraft/index.html')
    assert response.status_code == 200

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.items = []

        def handle_starttag(self, tag, attrs):
            if tag == 'link':
                self.items.append(dict(attrs))

    links = Links()
    links.feed(response.text)
    wasm, module, font, style = links.items
    assert 'href' not in wasm and 'rel' not in wasm
    assert wasm['data-liberty-href'] == './word_bg.wasm'
    assert wasm['data-liberty-rel'] == 'preload'
    assert wasm['integrity'] == 'sha384-wasm'
    assert module['data-liberty-rel'] == 'modulepreload'
    assert module['data-liberty-href'] == './word.js'
    assert module['integrity'] == 'sha384-module'
    assert module['crossorigin'] == 'anonymous'
    assert font['href'] == './font.woff2' and font['rel'] == 'preload'
    assert style['href'] == './editor.css' and style['rel'] == 'stylesheet'


@pytest.mark.parametrize('optional_attributes', ['as', 'type', 'as type'])
def test_native_preload_optional_boolean_attributes_do_not_break_launch(env, optional_attributes):
    _, client, settings = env
    target = settings.apps_dir / 'wordcraft'
    target.mkdir(parents=True)
    (target / 'index.html').write_text(
        '<html><head><link rel="preload" href="./word.wasm" ' + optional_attributes
        + '></head><body></body></html>')
    response = client.get(settings.demo_editor_origin + '/demo/runtime/wordcraft/index.html')
    assert response.status_code == 200
    assert 'data-liberty-href="./word.wasm"' in response.text


def test_demo_controller_is_isolated_no_store_and_has_no_private_adapters(env):
    _, client, settings = env
    path = '/demo/controller'
    response = client.get(settings.demo_editor_origin + path)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert 'frame-ancestors ' + settings.origin in response.headers['content-security-policy']
    assert '/demo/controller-assets/demo-controller.mjs' in response.text
    assert settings.origin in response.text
    for origin in [settings.origin, settings.editor_origin]:
        assert client.get(origin + path).status_code == 404
        assert client.get(origin + '/demo/controller-assets/demo-session.mjs').status_code == 404
    for name in ['demo-controller.mjs', 'demo-session.mjs']:
        code = client.get(settings.demo_editor_origin + '/demo/controller-assets/' + name)
        assert code.status_code == 200 and 'javascript' in code.headers['content-type']
        assert code.headers['cache-control'] == 'no-store'
    for name in ['editor-host.mjs', 'bridge.mjs', 'editor-storage.mjs', '../mfa.key', 'config.json']:
        assert client.get(settings.demo_editor_origin + '/demo/controller-assets/' + name).status_code == 404
    assert client.post(settings.demo_editor_origin + path).status_code == 404
