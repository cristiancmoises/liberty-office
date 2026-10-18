import hashlib,json,secrets,re
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import FileResponse,HTMLResponse,RedirectResponse
from .security import full,svc,authorize,digest,uid,now
from .i18n import translate
from .assets import asset_response,prepare_public_html,public_location
from .public_assets import _file

router=APIRouter()
LOCK=Path(__file__).resolve().parents[1]/'upstream.lock.json'
APPS=json.loads(LOCK.read_text())['apps'];IDS={a['id'] for a in APPS}
STATIC=Path(__file__).parent/'static'

@router.get('/api/apps')
def catalog(request: Request,session=Depends(full)):
    root=svc(request).settings.apps_dir
    return {'apps':[{k:translate(v,request) if k in ('description','category') else v for k,v in a.items() if k not in ('url','sha256','size')} |
      {'installed':(root/a['id']/'index.html').is_file(),'launch_url':'/api/editors/'+a['id']} for a in APPS]}

@router.post('/api/editors/{app_id}')
def launch(app_id: str,request: Request,session=Depends(full)):
    service=svc(request)
    if app_id not in IDS:raise HTTPException(404,'Aplicativo não encontrado.')
    if not (service.settings.apps_dir/app_id/'index.html').is_file():raise HTTPException(503,'Pacote web não instalado.')
    token,nonce,handle=secrets.token_urlsafe(32),secrets.token_urlsafe(24),uid()
    with service.db.transaction() as c:
        current=authorize(c,session)
        c.execute('DELETE FROM editor_tickets WHERE expires<=?',(now(),))
        if c.execute('SELECT COUNT(*) FROM editor_tickets WHERE session_id=?',(session['id'],)).fetchone()[0]>=16:
            raise HTTPException(429,'Feche um editor antes de abrir outro.')
        c.execute('INSERT INTO editor_tickets VALUES(?,?,?,?,?,?)',(digest(token),handle,session['id'],app_id,nonce,current['expires']))
    return {'url':service.settings.editor_origin+'/runtime/'+token+'/index.html','origin':service.settings.editor_origin,
            'nonce':nonce,'ticket_id':handle}

@router.delete('/api/editors/{handle}')
def close(handle: str,request: Request,session=Depends(full)):
    with svc(request).db.transaction() as c:
        authorize(c,session)
        c.execute('DELETE FROM editor_tickets WHERE handle=? AND session_id=?',(handle,session['id']))
    return {'ok':True}

@router.get('/apps/{app_id}/{asset:path}')
def legacy_asset(app_id: str,asset: str,request: Request,session=Depends(full)):
    if app_id not in IDS or '..' in Path(asset).parts:raise HTTPException(404,'Arquivo não encontrado.')
    raise HTTPException(410,'Abra o aplicativo pelo portal. Editores agora usam uma origem isolada.')

def valid_ticket(service,token):
    if not 30<=len(token)<=100:raise HTTPException(401,'Sessão do editor inválida ou expirada.')
    with service.db.connect() as c:
        row=c.execute("""SELECT t.*,s.user_id FROM editor_tickets t JOIN sessions s ON s.id=t.session_id
          JOIN users u ON u.id=s.user_id WHERE t.id=? AND t.expires>? AND s.expires>?
          AND s.stage='full' AND u.enabled=1 AND u.totp_confirmed=1""",(digest(token),now(),now())).fetchone()
    if not row:raise HTTPException(401,'Sessão do editor inválida ou expirada.')
    return dict(row)

@router.api_route('/runtime/{token}/{asset:path}',methods=['GET','HEAD'])
def runtime(token: str,asset: str,request: Request):
    service=svc(request);ticket=valid_ticket(service,token)
    if asset.startswith('__liberty/'):
        name=asset.removeprefix('__liberty/')
        if name not in ('bridge.mjs','editor-host.mjs','editor-storage.mjs','editor-runtime.mjs','light-editor.mjs','light-editor.css','i18n.mjs','translations.mjs','canvas-density.mjs'):raise HTTPException(404,'Adaptador não encontrado.')
        return FileResponse(STATIC/name,media_type='text/css' if name.endswith('.css') else 'text/javascript')
    config={'portalOrigin':service.settings.origin,'nonce':ticket['nonce'],'maxBytes':service.settings.max_upload,'appId':ticket['app_id'],
            'identity':hashlib.sha256(('editor:'+ticket['user_id']).encode()).hexdigest()}
    data=json.dumps(config,ensure_ascii=True).replace('<','\\u003c')
    injection='<script id="__liberty-config" type="application/json">'+data+'</script>'
    injection+='<script type="module" src="./__liberty/editor-host.mjs"></script>'
    return serve_bundle(service.settings,ticket['app_id'],asset,request,injection)

def defer_native_preloads(html: str) -> str:
    """Make native-code hints inert before the browser's preload scanner runs."""
    offsets = [0, *(match.end() for match in re.finditer('\n', html))]
    replacements = []

    class Preloads(HTMLParser):
        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag != 'link':
                return
            values = dict(attrs)
            rel = (values.get('rel') or '').lower().split()
            native = 'modulepreload' in rel or ('preload' in rel and (
                (values.get('as') or '').lower() == 'script'
                or (values.get('type') or '').lower() == 'application/wasm'
                or urlsplit(values.get('href') or '').path.lower().endswith(('.wasm', '.js'))))
            if not native:
                return
            rendered = []
            for name, value in attrs:
                name = 'data-liberty-' + name if name in ('rel', 'href') else name
                rendered.append(' ' + name + ('' if value is None else '="' + escape(value, quote=True) + '"'))
            line, column = self.getpos()
            start = offsets[line - 1] + column
            raw = self.get_starttag_text()
            assert raw is not None
            replacements.append((start, start + len(raw), '<link' + ''.join(rendered) + '>'))

    Preloads(convert_charrefs=False).feed(html)
    for start, end, replacement in reversed(replacements):
        html = html[:start] + replacement + html[end:]
    return html


def serve_bundle(settings,app_id,asset,request,injection):
    """Serve pinned assets after the calling route has authorized its runtime."""
    try:
        path=_file(settings.apps_dir,app_id+'/'+asset)
    except ValueError:
        raise HTTPException(404,'Arquivo do aplicativo não encontrado.') from None
    if path.name in ('sw.js','sw.js.gz','installed.json'):
        raise HTTPException(404,'Arquivo do aplicativo não encontrado.')
    if asset=='index.html':
        # Installation verifies and prepares editor assets; serving adds the adapter.
        html=defer_native_preloads(prepare_public_html(path.read_text(),app_id,request))
        html=re.sub(r'(<script\b[^>]*?\btype\s*=\s*)([\"\'])module\2',lambda m:m.group(1)+m.group(2)+'application/x-liberty-module'+m.group(2),html,flags=re.I)
        html=html.replace('<head>','<head>'+injection,1) if '<head>' in html else injection+html
        return HTMLResponse(html)
    if location:=public_location(request,app_id,asset):
        return RedirectResponse(location,status_code=307)
    return asset_response(path,request)
