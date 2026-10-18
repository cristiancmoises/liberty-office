from pathlib import Path
from urllib.parse import urlsplit
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .config import Settings
from .db import DB
from .security import Service
from .locks import VolumeLock
from . import auth, admin
from .i18n import translate


def create_app(settings=None):
    settings=settings or Settings.from_env()
    from .public_assets import load_public_generations
    public_assets=load_public_generations(settings.public_assets_dir) if settings.public_assets_dir else None
    settings.data_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    volume=VolumeLock(settings.data_dir).acquire()
    try:
        settings.data_dir.chmod(0o700)
        for name in ('blobs','tmp'):
            (settings.data_dir/name).mkdir(mode=0o700,exist_ok=True)
        service=Service(settings,DB(settings.data_dir/'liberty.db'))
    except BaseException:
        volume.release();raise
    @asynccontextmanager
    async def lifespan(app):
        try:
            with service.db.transaction() as c:
                c.execute('DELETE FROM reservations')
            for item in (settings.data_dir/'tmp').iterdir():
                if item.is_file(): item.unlink()
            yield
        finally:
            volume.release()
    app=FastAPI(title='Liberty Office',version=__version__,docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.svc=service
    app.state.public_assets=public_assets
    @app.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        return JSONResponse({'detail':[{**{key:error[key] for key in ('loc','msg','type')},'msg':translate(error['msg'],request)} for error in exc.errors()]},status_code=422)
    @app.exception_handler(HTTPException)
    async def http_error(request,exc):
        return JSONResponse({'detail':translate(exc.detail,request)},status_code=exc.status_code,headers=exc.headers)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=[urlsplit(origin).hostname for origin in (settings.origin,settings.editor_origin,settings.demo_editor_origin)])

    @app.middleware('http')
    async def security_headers(request: Request,call_next):
        from .http_security import handle
        return await handle(request,call_next,service)

    app.include_router(auth.router)
    app.include_router(admin.router)
    # Components are imported here to keep CLI/database operations independent of web routing.
    from . import drive, catalog, demo, assets
    app.include_router(drive.router)
    app.include_router(catalog.router)
    app.include_router(demo.router)
    app.include_router(assets.router)
    static=Path(__file__).parent/'static'
    app.mount('/static',StaticFiles(directory=static),name='static')

    @app.get('/source.zip')
    def source_offer(request: Request):
        source=settings.source_archive
        if not source.is_file():
            return JSONResponse({'detail':translate('A oferta de código fonte está incluída na imagem Docker e no pacote de distribuição.',request)},status_code=404)
        return FileResponse(source,media_type='application/zip',filename='liberty-office-source.zip')

    @app.get('/healthz')
    def health():
        with service.db.connect() as c:
            c.execute('SELECT 1').fetchone()
        return {'status':'ok','version':__version__}

    @app.get('/')
    def index():
        return FileResponse(static/'index.html')

    return app
