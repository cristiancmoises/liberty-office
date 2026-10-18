"""Anonymous demonstration: pinned assets on a third, unprivileged origin."""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .catalog import APPS, IDS, STATIC, serve_bundle
from .security import svc
from .i18n import translate

router = APIRouter()


@router.get('/demo')
def demo_page():
    return FileResponse(STATIC / 'demo.html')


@router.get('/demo/apps')
def demo_apps(request: Request):
    settings = svc(request).settings
    return {'apps': [
        {key: translate(value,request) if key in ('description','category') else value for key, value in app.items() if key in ('id', 'name', 'description', 'monogram', 'category')}
        | {'installed': (settings.apps_dir / app['id'] / 'index.html').is_file(),
           'url': settings.demo_editor_origin + '/demo/runtime/' + app['id'] + '/index.html'}
        for app in APPS
    ]}


@router.api_route('/demo/runtime/{app_id}/{asset:path}', methods=['GET', 'HEAD'])
def demo_runtime(app_id: str, asset: str, request: Request):
    if app_id not in IDS:
        raise HTTPException(404, 'Aplicativo não encontrado.')
    if asset.startswith('__liberty/'):
        name = asset.removeprefix('__liberty/')
        if name not in ('demo-host.mjs', 'demo-guard.mjs', 'demo-download.mjs', 'bridge.mjs', 'editor-runtime.mjs', 'editor-storage.mjs', 'light-editor.mjs', 'light-editor.css', 'i18n.mjs', 'translations.mjs', 'canvas-density.mjs'):
            raise HTTPException(404, 'Adaptador não encontrado.')
        return FileResponse(STATIC / name, media_type='text/css' if name.endswith('.css') else 'text/javascript')
    service = svc(request)
    data = json.dumps({'portalOrigin': service.settings.origin, 'appId': app_id}, ensure_ascii=True).replace('<', '\\u003c')
    injection = '<script id="__liberty-config" type="application/json">' + data + '</script>'
    injection += '<script type="module" src="./__liberty/demo-host.mjs"></script>'
    return serve_bundle(service, app_id, asset, request, injection)
