from pathlib import Path
from urllib.parse import urlsplit
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .config import Settings
from .db import DB
from .security import Service
from .locks import VolumeLock
from . import auth, admin


def create_app(settings=None):
    settings=settings or Settings.from_env()
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
    @app.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        return JSONResponse({'detail':[{key:error[key] for key in ('loc','msg','type')} for error in exc.errors()]},status_code=422)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=[urlsplit(settings.origin).hostname,urlsplit(settings.editor_origin).hostname])

    @app.middleware('http')
    async def security_headers(request: Request,call_next):
        from .http_security import handle
        return await handle(request,call_next,service)

    app.include_router(auth.router)
    app.include_router(admin.router)
    # Components are imported here to keep CLI/database operations independent of web routing.
    from . import drive, catalog
    app.include_router(drive.router)
    app.include_router(catalog.router)
    static=Path(__file__).parent/'static'
    app.mount('/static',StaticFiles(directory=static),name='static')

    @app.get('/source.zip')
    def source_offer():
        source=settings.source_archive
        if not source.is_file():
            return JSONResponse({'detail':'A oferta de código fonte está incluída na imagem Docker e no pacote de distribuição.'},status_code=404)
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
