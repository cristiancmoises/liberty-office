import hashlib,json,mimetypes,secrets,re
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import FileResponse,HTMLResponse
from .security import full,svc,authorize,digest,uid,now

router=APIRouter()
LOCK=Path(__file__).resolve().parents[1]/'upstream.lock.json'
APPS=json.loads(LOCK.read_text())['apps'];IDS={a['id'] for a in APPS}
STATIC=Path(__file__).parent/'static'

@router.get('/api/apps')
def catalog(request: Request,session=Depends(full)):
    root=svc(request).settings.apps_dir
    return {'apps':[{k:v for k,v in a.items() if k not in ('url','sha256','size')} |
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

@router.get('/runtime/{token}/{asset:path}')
def runtime(token: str,asset: str,request: Request):
    service=svc(request);ticket=valid_ticket(service,token)
    if asset.startswith('__liberty/'):
        name=asset.removeprefix('__liberty/')
        if name not in ('bridge.mjs','editor-host.mjs','editor-storage.mjs','editor-runtime.mjs','light-editor.mjs','light-editor.css'):raise HTTPException(404,'Adaptador não encontrado.')
        return FileResponse(STATIC/name,media_type='text/css' if name.endswith('.css') else 'text/javascript')
    config={'portalOrigin':service.settings.origin,'nonce':ticket['nonce'],'maxBytes':service.settings.max_upload,'appId':ticket['app_id'],
            'identity':hashlib.sha256(('editor:'+ticket['user_id']).encode()).hexdigest()}
    data=json.dumps(config,ensure_ascii=True).replace('<','\\u003c')
    injection='<script id="__liberty-config" type="application/json">'+data+'</script>'
    injection+='<script type="module" src="./__liberty/editor-host.mjs"></script>'
    return serve_bundle(service,ticket['app_id'],asset,request,injection)

def serve_bundle(service,app_id,asset,request,injection):
    """Serve pinned assets after the calling route has authorized its runtime."""
    root=(service.settings.apps_dir/app_id).resolve();path=(root/asset).resolve()
    if not path.is_relative_to(root) or not path.is_file() or any(p.startswith('.') for p in Path(asset).parts):
        raise HTTPException(404,'Arquivo do aplicativo não encontrado.')
    if asset=='index.html':
        # Original WASM/assets remain untouched. The served HTML adds only the Liberty adapter.
        html=path.read_text()
        html=re.sub(r'(<script\b[^>]*?\btype\s*=\s*)([\"\'])module\2',lambda m:m.group(1)+m.group(2)+'application/x-liberty-module'+m.group(2),html,flags=re.I)
        html=html.replace('<head>','<head>'+injection,1) if '<head>' in html else injection+html
        return HTMLResponse(html)
    media='application/wasm' if path.suffix=='.wasm' else mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    headers={}
    if path.suffix in ('.wasm','.js') and 'gzip' in request.headers.get('accept-encoding','') and path.with_name(path.name+'.gz').is_file():
        path=path.with_name(path.name+'.gz');headers={'Content-Encoding':'gzip','Vary':'Accept-Encoding'}
    return FileResponse(path,media_type=media,headers=headers)
