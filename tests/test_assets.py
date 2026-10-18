import gzip
import hashlib
import json
import os
from pathlib import Path

import pytest
from conftest import bootstrap, csrf
from fastapi import HTTPException

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/encoded-asset.json").read_text()
)
PLAIN = bytes.fromhex(FIXTURE["plain"])
BROTLI = bytes.fromhex(FIXTURE["br"])


@pytest.fixture
def representations(tmp_path):
    path = tmp_path / "engine.wasm"
    path.write_bytes(PLAIN)
    path.with_name(path.name + ".gz").write_bytes(gzip.compress(PLAIN, mtime=0))
    path.with_name(path.name + ".br").write_bytes(BROTLI)
    return path


@pytest.mark.parametrize(
    ("accepted", "encoding"),
    [
        ("gzip;q=0, identity;q=1", None),
        ("br, gzip", "br"),
        ("br;q=0, gzip;q=0.8", "gzip"),
        ("br;q=0.3, gzip;q=0.8, identity;q=0.1", "gzip"),
        ("gzip;q=0.2, identity;q=0.9", None),
        ("gzip;q=0.8", "gzip"),
        ("*;q=0, gzip;q=1", "gzip"),
        ("gzip;q=0", None),
        ("gzip;q=0, br;q=0, identity;q=0", "forbidden"),
    ],
)
def test_http_encoding_priorities_and_exclusions(env, accepted, encoding):
    _, client, settings = env
    target = settings.apps_dir / "wordcraft"
    target.mkdir(parents=True)
    (target / "engine.wasm").write_bytes(PLAIN)
    (target / "engine.wasm.gz").write_bytes(gzip.compress(PLAIN, mtime=0))
    (target / "engine.wasm.br").write_bytes(BROTLI)
    url = settings.demo_editor_origin + "/demo/runtime/wordcraft/engine.wasm"
    response, body = raw(client, "GET", url, {"Accept-Encoding": accepted})
    assert response.status_code == (406 if encoding == "forbidden" else 200)
    if encoding != "forbidden":
        assert response.headers.get("content-encoding") == encoding
        assert (
            body
            == {None: PLAIN, "gzip": gzip.compress(PLAIN, mtime=0), "br": BROTLI}[
                encoding
            ]
        )


@pytest.mark.parametrize(
    ("accepted", "encoding"),
    [
        (None, None),
        ("", None),
        ("identity", None),
        ("unknown", None),
        ("gzip;q=0.8", "gzip"),
        ("br, gzip, identity", "br"),
        (" GZip ; Q=0.500 , BR ; q=0.500 ", "br"),
        ("gzip;q=0, identity;q=1", None),
        ("gzip;q=0", None),
        ("*", "br"),
        ("*;q=0.5, br;q=0", "gzip"),
        ("*;q=0, gzip;q=1", "gzip"),
        ("*;q=0, identity;q=0.1", None),
        ("br;q=0.001, gzip;q=0, identity;q=0", "br"),
        ("br;q=1.000, gzip;q=1.", "br"),
        ("br;q=0., gzip;q=1", "gzip"),
        ("br;q=0.1, br;q=0.9, gzip;q=0.2", "gzip"),
        ("br;q=0, br;q=1", None),
        ("br;q=NaN, *;q=1", "gzip"),
        ("br;q=.8, gzip;q=0.1", "gzip"),
        ("br;q=1.001, gzip", "gzip"),
        ("br;q=0.1234, gzip", "gzip"),
        ("br;q=0.8;q=1, gzip", "gzip"),
        ("br;q=1, br;q=invalid, gzip", "gzip"),
        ("br;foo=1, gzip", "gzip"),
    ],
)
def test_encoding_priorities_exclusions_and_identity(
    representations, accepted, encoding
):
    from liberty.assets import select_representation

    selected, actual_encoding = select_representation(representations, accepted)
    assert actual_encoding == encoding
    suffix = {None: "", "br": ".br", "gzip": ".gz"}[encoding]
    assert selected == representations.with_name(representations.name + suffix)


@pytest.mark.parametrize(
    "accepted", ["*;q=0", "gzip;q=0, identity;q=0", "identity;q=0"]
)
def test_forbidden_representations_fail_closed(representations, accepted):
    from liberty.assets import select_representation

    with pytest.raises(HTTPException) as failure:
        select_representation(representations, accepted)
    assert failure.value.status_code == 406


def test_only_installed_regular_representations_are_selected(representations, tmp_path):
    from liberty.assets import select_representation

    variant = representations.with_name(representations.name + ".br")
    variant.unlink()
    assert select_representation(representations, "br, gzip")[1] == "gzip"
    outside = tmp_path / "private"
    outside.write_bytes(b"not a public asset")
    variant.symlink_to(outside)
    assert select_representation(representations, "br, gzip")[1] == "gzip"
    assert select_representation(representations, "br")[1] is None
    with pytest.raises(HTTPException) as failure:
        select_representation(representations, "br, identity;q=0")
    assert failure.value.status_code == 406


def test_repeated_encoding_headers_cannot_reenable_an_excluded_coding(env):
    _, client, settings = env
    target = settings.apps_dir / "wordcraft"
    target.mkdir(parents=True)
    (target / "engine.wasm").write_bytes(PLAIN)
    (target / "engine.wasm.gz").write_bytes(gzip.compress(PLAIN, mtime=0))
    url = settings.demo_editor_origin + "/demo/runtime/wordcraft/engine.wasm"
    response, body = raw(
        client,
        "GET",
        url,
        [
            ("Accept-Encoding", "gzip"),
            ("Accept-Encoding", "gzip;q=0"),
        ],
    )
    assert response.status_code == 200 and body == PLAIN
    assert "content-encoding" not in response.headers


def raw(client, method, url, headers):
    response = client.send(
        client.build_request(method, url, headers=headers), stream=True
    )
    try:
        return response, b"".join(response.iter_raw())
    finally:
        response.close()


def test_encoded_mime_vary_etag_and_ranges(env):
    _, client, settings = env
    target = settings.apps_dir / "wordcraft"
    target.mkdir(parents=True)
    encoded = {"identity": PLAIN, "gzip": gzip.compress(PLAIN, mtime=0), "br": BROTLI}
    for name, data in encoded.items():
        suffix = {"identity": "", "gzip": ".gz", "br": ".br"}[name]
        (target / ("engine.wasm" + suffix)).write_bytes(data)
    url = settings.demo_editor_origin + "/demo/runtime/wordcraft/engine.wasm"
    etags = {}
    for encoding, data in encoded.items():
        headers = {"Accept-Encoding": encoding}
        response, body = raw(client, "GET", url, headers)
        assert response.status_code == 200 and body == data
        assert response.headers["content-type"] == "application/wasm"
        assert response.headers["vary"].lower() == "accept-encoding"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["content-length"] == str(len(data))
        etags[encoding] = response.headers["etag"]
        assert etags[encoding] == '"' + hashlib.sha256(data).hexdigest() + '"'
        if encoding == "gzip":
            assert gzip.decompress(body) == PLAIN
        head, body = raw(client, "HEAD", url, headers)
        assert head.status_code == 200 and body == b""
        assert head.headers["etag"] == etags[encoding]
        assert head.headers["content-length"] == str(len(data))
        for condition in [
            etags[encoding],
            "W/" + etags[encoding],
            "*",
            '"other", ' + etags[encoding],
        ]:
            unchanged, body = raw(
                client, "GET", url, headers | {"If-None-Match": condition}
            )
            assert unchanged.status_code == 304 and body == b""
            assert unchanged.headers["etag"] == etags[encoding]
            assert unchanged.headers["vary"].lower() == "accept-encoding"
        partial, body = raw(client, "GET", url, headers | {"Range": "bytes=2-5"})
        assert partial.status_code == 206 and body == data[2:6]
        assert partial.headers["content-range"] == f"bytes 2-5/{len(data)}"
        matching, body = raw(
            client,
            "GET",
            url,
            headers | {"Range": "bytes=2-5", "If-Range": etags[encoding]},
        )
        assert matching.status_code == 206 and body == data[2:6]
        changed, body = raw(
            client, "GET", url, headers | {"Range": "bytes=2-5", "If-Range": '"other"'}
        )
        assert changed.status_code == 200 and body == data
    assert len(set(etags.values())) == 3
    response, body = raw(
        client,
        "GET",
        url,
        {"Accept-Encoding": "identity", "If-None-Match": etags["gzip"]},
    )
    assert response.status_code == 200 and body == PLAIN
    unchanged = client.get(
        url,
        headers={
            "Accept-Encoding": "identity",
            "If-Modified-Since": response.headers["last-modified"],
        },
    )
    assert unchanged.status_code == 304
    stale = client.get(
        url,
        headers={
            "Accept-Encoding": "identity",
            "If-None-Match": '"other"',
            "If-Modified-Since": response.headers["last-modified"],
        },
    )
    assert stale.status_code == 200
    stat = (target / "engine.wasm").stat()
    (target / "engine.wasm").write_bytes(b"changed!")
    os.utime(target / "engine.wasm", ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed = client.get(
        url, headers={"Accept-Encoding": "identity", "If-None-Match": etags["identity"]}
    )
    assert changed.status_code == 200 and changed.headers["etag"] != etags["identity"]


def test_private_assets_negotiate_only_after_runtime_authorization(env):
    _, client, settings = env
    bootstrap(client, settings)
    target = settings.apps_dir / "wordcraft"
    target.mkdir(parents=True)
    (target / "index.html").write_text("<html></html>")
    (target / "engine.wasm").write_bytes(PLAIN)
    (target / "engine.wasm.gz").write_bytes(gzip.compress(PLAIN, mtime=0))
    ticket = client.post("/api/editors/wordcraft", headers=csrf(client)).json()
    url = ticket["url"].rsplit("/", 1)[0] + "/engine.wasm"
    response, body = raw(
        client, "GET", url, {"Accept-Encoding": "gzip;q=0, identity;q=1"}
    )
    assert response.status_code == 200 and body == PLAIN
    assert "content-encoding" not in response.headers
    assert (
        client.delete(
            "/api/editors/" + ticket["ticket_id"], headers=csrf(client)
        ).status_code
        == 200
    )
    assert client.head(url, headers={"Accept-Encoding": "gzip"}).status_code == 401
