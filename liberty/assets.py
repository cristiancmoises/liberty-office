"""Deliver installed editor representations without overriding client exclusions."""

import hashlib
import mimetypes
import re
from email.utils import parsedate_to_datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from .public_assets import _file, build_public_manifest, load_public_manifest

__all__ = [
    "build_public_manifest",
    "load_public_manifest",
    "public_asset",
    "select_representation",
]

router = APIRouter()

QUALITY = re.compile(r"(?:0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)")


def _qualities(accepted: str) -> dict[str, int]:
    qualities: dict[str, int] = {}
    for item in accepted.split(","):
        coding, *parameters = (part.strip().lower() for part in item.split(";"))
        if coding not in ("br", "gzip", "identity", "*"):
            continue
        quality = 1000
        if parameters:
            name, separator, value = parameters[0].partition("=")
            if (
                len(parameters) != 1
                or name != "q"
                or not separator
                or not QUALITY.fullmatch(value)
            ):
                quality = 0
            else:
                whole, _, fraction = value.partition(".")
                quality = int(whole) * 1000 + int(fraction.ljust(3, "0"))
        # Conflicting or malformed duplicates never re-enable an exclusion.
        qualities[coding] = min(qualities.get(coding, 1000), quality)
    return qualities


def select_representation(
    path: Path, accept_encoding: str | None
) -> tuple[Path, str | None]:
    """Select an installed file; equal explicit weights prefer br, gzip, identity.

    No header selects identity. Implicitly acceptable identity is a fallback
    behind any positively offered coding, not an invented client weight.
    """
    if not path.is_file():
        raise HTTPException(404, "Editor asset not found.")
    if not accept_encoding:
        return path, None
    qualities = _qualities(accept_encoding)
    candidates: list[tuple[int, int, Path, str | None]] = []
    for coding, suffix, preference in [("br", ".br", 2), ("gzip", ".gz", 1)]:
        quality = qualities.get(coding, qualities.get("*", 0))
        variant = path.with_name(path.name + suffix)
        if quality > 0 and not variant.is_symlink() and variant.is_file():
            candidates.append((quality, preference, variant, coding))
    identity = qualities.get("identity")
    if identity is not None and identity > 0:
        candidates.append((identity, 0, path, None))
    elif identity is None and qualities.get("*") != 0:
        candidates.append((0, 0, path, None))
    if not candidates:
        raise HTTPException(
            406,
            "No acceptable editor representation.",
            headers={"Vary": "Accept-Encoding"},
        )
    _, _, selected, encoding = max(candidates, key=lambda candidate: candidate[:2])
    return selected, encoding


def asset_response(
    path: Path, request: Request, *, expected_hashes: dict[str, str] | None = None
) -> Response:
    """Keep MIME, validators and ranges tied to the selected encoded bytes."""
    selected, encoding = select_representation(
        path, ",".join(request.headers.getlist("accept-encoding"))
    )
    media = (
        "application/wasm"
        if path.suffix == ".wasm"
        else mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    )
    with selected.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if expected_hashes is not None and digest != expected_hashes.get(
        encoding or "identity"
    ):
        raise HTTPException(404, "Public asset integrity check failed.")
    etag = '"' + digest + '"'
    headers = {"Vary": "Accept-Encoding", "ETag": etag}
    if encoding:
        headers["Content-Encoding"] = encoding
    stat = selected.stat()
    response = FileResponse(
        selected, media_type=media, headers=headers, stat_result=stat
    )
    condition = request.headers.get("if-none-match")
    unchanged = False
    if condition is not None:
        unchanged = any(
            tag.strip().removeprefix("W/") in ("*", etag)
            for tag in condition.split(",")
        )
    elif modified_since := request.headers.get("if-modified-since"):
        try:
            date = parsedate_to_datetime(modified_since)
            unchanged = date.tzinfo is not None and int(stat.st_mtime) <= int(
                date.timestamp()
            )
        except (ValueError, TypeError, OverflowError, OSError):
            pass
    if unchanged:
        return Response(
            status_code=304,
            headers={
                key: response.headers[key]
                for key in ("etag", "last-modified", "vary", "content-encoding")
                if key in response.headers
            },
        )
    return response


def public_location(request: Request, app_id: str, asset: str) -> str | None:
    registry = getattr(request.app.state, "public_assets", None)
    if registry and asset in registry["generations"][registry["current"]]["apps"].get(
        app_id, {}
    ):
        return "/public-assets/" + registry["current"] + "/" + app_id + "/" + asset
    return None


def prepare_public_html(html: str, app_id: str, request: Request) -> str:
    # This exact trusted upstream block caches injected HTML despite no-store.
    registration = re.compile(
        r'if\s*\("serviceWorker" in navigator && !new URLSearchParams\(location.search\).has\("nosw"\)\)\s*\{\s*'
        r'navigator.serviceWorker.register\("sw.js"\).catch\(\(e\) => console.warn\("service worker:", e\)\);\s*\}'
    )
    html = registration.sub("", html)
    if "serviceWorker.register" in html:
        raise HTTPException(503, "Unreviewed editor service worker registration.")
    registry = getattr(request.app.state, "public_assets", None)
    if not registry:
        return html
    files = registry["generations"][registry["current"]]["apps"].get(app_id, {})
    for name in files:
        url = public_location(request, app_id, name)
        assert url is not None
        pattern = re.compile(r'(["\'])(?:\./)?' + re.escape(name) + r'(\?[^"\'<>]*)?\1')
        html = pattern.sub(
            lambda match, url=url: match[1] + url + (match[2] or "") + match[1], html
        )
    return html


@router.api_route(
    "/public-assets/{generation}/{app_id}/{asset:path}", methods=["GET", "HEAD"]
)
def public_asset(
    generation: str, app_id: str, asset: str, request: Request
) -> Response:
    registry = getattr(request.app.state, "public_assets", None)
    if not registry:
        raise HTTPException(404, "Public asset not found.")
    entry = (
        registry["generations"]
        .get(generation, {})
        .get("apps", {})
        .get(app_id, {})
        .get(asset)
    )
    if not entry:
        raise HTTPException(404, "Public asset not found.")
    try:
        path = _file(registry["root"], generation + "/" + app_id + "/" + asset)
    except ValueError:
        raise HTTPException(404, "Public asset not found.") from None
    response = asset_response(
        path,
        request,
        expected_hashes={
            encoding: metadata["sha256"]
            for encoding, metadata in entry["representations"].items()
        },
    )
    request.state.validated_public_asset = True
    return response
