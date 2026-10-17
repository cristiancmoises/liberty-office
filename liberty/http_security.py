import asyncio,re,secrets
from urllib.parse import urlsplit
from fastapi.responses import JSONResponse

EXEMPT={'/api/auth/login','/api/auth/bootstrap','/api/auth/activate','/api/auth/password-reset'}
UPLOAD=re.compile(r'^/api/files(?:/[^/]+/content)?$')

def decorate(response,editor,settings):
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cache-Control']='no-store'
    response.headers['Permissions-Policy']='camera=(), geolocation=(), payment=()'
    if editor:
        if 'x-frame-options' in response.headers:del response.headers['x-frame-options']
        response.headers['Content-Security-Policy']=("default-src 'self'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; "
            "connect-src 'self' blob:; media-src 'self' blob:; worker-src 'self' blob:; "
            "frame-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'none'; frame-ancestors "+settings.origin)
    else:
        response.headers['X-Frame-Options']='DENY'
        response.headers.setdefault('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-src "+settings.editor_origin+"; "
            "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
    if settings.secure:response.headers['Strict-Transport-Security']='max-age=31536000'
    return response

async def handle(request,call_next,service):
    cfg=service.settings;host=request.headers.get('host','').lower()
    portal=host==urlsplit(cfg.origin).netloc.lower();editor=host==urlsplit(cfg.editor_origin).netloc.lower()
    def reject(status,message):return decorate(JSONResponse({'detail':message},status_code=status),editor,cfg)
    path=request.url.path
    if not portal and not editor:return reject(400,'Host não autorizado.')
    if editor and not (path.startswith('/runtime/') or path=='/healthz'):return reject(404,'Recurso não encontrado.')
    if portal and path.startswith('/runtime/'):return reject(404,'Abra os editores na origem isolada.')
    if request.method not in ('GET','HEAD','OPTIONS'):
        if not portal:return reject(404,'Recurso não encontrado.')
        if request.headers.get('origin')!=cfg.origin:return reject(403,'Origem não autorizada.')
        if path.startswith('/api/') and path not in EXEMPT:
            session=service.session(request)
            if not session:return reject(401,'Sessão expirada. Entre novamente sem fechar o editor.')
            if not secrets.compare_digest(request.headers.get('x-csrf-token',''),session['csrf']):
                return reject(403,'Token CSRF ausente ou inválido.')
        is_upload=(request.method=='POST' and path=='/api/files') or (request.method=='PUT' and UPLOAD.fullmatch(path))
        if path.startswith('/api/') and not is_upload:
            raw=request.headers.get('content-length')
            try:
                if raw is not None and (len(raw)>10 or not 0<=int(raw)<=16384):return reject(413,'Corpo JSON excede 16 KiB.')
            except ValueError:return reject(400,'Content-Length inválido.')
            chunks=[];total=0
            try:
                async with asyncio.timeout(10):
                    async for chunk in request.stream():
                        total+=len(chunk)
                        if total>16384:return reject(413,'Corpo JSON excede 16 KiB.')
                        chunks.append(chunk)
            except TimeoutError:return reject(408,'Tempo de envio excedido.')
            # Starlette's cached Request replays this bounded body to FastAPI.
            request._body=b''.join(chunks)
    return decorate(await call_next(request),editor,cfg)
