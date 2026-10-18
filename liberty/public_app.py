"""Read-only public delivery without private storage, sessions or a database."""

from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from . import __version__, assets, demo
from .catalog import STATIC
from .config import Settings
from .http_security import decorate
from .i18n import language, translate
from .public_assets import _file, load_public_generations

PUBLIC_STATIC = frozenset(
    (
        "maintenance.mjs",
        "maintenance.css",
        "liberty.svg",
        "fonts.css",
        "style.css",
        "editor-layout.css",
        "demo.css",
        "demo.mjs",
        "i18n.mjs",
        "translations.mjs",
        "view-controls.mjs",
        "demo-download.mjs",
        "demo-session.mjs",
        "demo-policy.mjs",
        "bridge.mjs",
    )
)


def create_public_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    registry = (
        load_public_generations(settings.public_assets_dir)
        if settings.public_assets_dir
        else None
    )
    app = FastAPI(
        title="Liberty Office public delivery",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.public_assets = registry

    @app.middleware("http")
    async def public_boundary(request: Request, call_next):
        host = request.headers.get("host", "").lower()
        portal = host == urlsplit(settings.origin).netloc.lower()
        isolated = host == urlsplit(settings.demo_editor_origin).netloc.lower()
        private = host == urlsplit(settings.editor_origin).netloc.lower()
        path = request.url.path

        def reject(status, message):
            response = JSONResponse(
                {"detail": translate(message, request)}, status_code=status
            )
            response.headers["Content-Language"] = language(request)
            return decorate(response, isolated, settings, demo=isolated)

        if not (portal or isolated or private):
            return reject(400, "Host não autorizado.")
        if private and not path.startswith("/public-assets/"):
            return reject(404, "Recurso não encontrado.")
        if portal and (
            path.startswith(("/api/", "/runtime/", "/apps/")) or path == "/api"
        ):
            return reject(
                503,
                "Accounts and saves are under maintenance. The public demo remains available.",
            )
        if request.method not in ("GET", "HEAD"):
            return reject(404, "Recurso não encontrado.")
        isolated_path = path in ("/healthz", "/demo/controller") or path.startswith(
            ("/demo/runtime/", "/demo/controller-assets/", "/public-assets/")
        )
        if isolated and not isolated_path:
            return reject(404, "Recurso não encontrado.")
        if portal and path.startswith(("/demo/runtime/", "/demo/controller")):
            return reject(404, "Recurso não encontrado.")
        response = await call_next(request)
        return decorate(
            response,
            isolated,
            settings,
            demo=isolated,
            public_asset=getattr(request.state, "validated_public_asset", False),
        )

    app.include_router(demo.router)
    app.include_router(assets.router)

    @app.api_route("/", methods=["GET", "HEAD"])
    def home():
        return FileResponse(STATIC / "maintenance.html")

    @app.api_route("/static/{name}", methods=["GET", "HEAD"])
    def static(name: str):
        if name not in PUBLIC_STATIC:
            raise HTTPException(404, "Public resource not found.")
        try:
            path = _file(STATIC, name)
        except ValueError:
            raise HTTPException(404, "Public resource not found.") from None
        return FileResponse(
            path, media_type="text/javascript" if name.endswith(".mjs") else None
        )

    @app.api_route("/source.zip", methods=["GET", "HEAD"])
    def source_offer(request: Request):
        source = settings.source_archive
        if source.is_symlink() or not source.is_file():
            return JSONResponse(
                {
                    "detail": translate(
                        "A oferta de código fonte está incluída na imagem Docker e no pacote de distribuição.",
                        request,
                    )
                },
                status_code=404,
            )
        return FileResponse(
            source, media_type="application/zip", filename="liberty-office-source.zip"
        )

    @app.api_route("/healthz", methods=["GET", "HEAD"])
    def health():
        return {
            "status": "ok",
            "version": __version__,
            "mode": "public-only",
            "generation": registry["current"] if registry else None,
        }

    return app
