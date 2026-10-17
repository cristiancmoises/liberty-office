import base64
import gzip
import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest

from scripts.brand_apps import (
    data_ranges,
    patch_wasm,
    replacement_bytes,
    transform_bundle,
)


def leb(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result + bytes([value]))


def section(kind, payload):
    return bytes([kind]) + leb(len(payload)) + payload


def module(payload=b"OLD MARK", passive=False):
    # A custom section deliberately contains the same bytes: only data may change.
    data = (
        b"\x01"
        + (b"\x01" if passive else b"\x00\x41\x00\x0b")
        + leb(len(payload))
        + payload
    )
    return b"\x00asm\x01\x00\x00\x00" + section(0, b"\x01xCODE") + section(11, data)


def change(data, before=b"OLD MARK", after=b"NEW MARK"):
    return {
        "offset": data.index(before),
        "length": len(before),
        "original_sha256": hashlib.sha256(before).hexdigest(),
        "replacement_sha256": hashlib.sha256(after).hexdigest(),
        "count": 1,
        "replacement": after,
    }


@pytest.mark.parametrize("passive", [False, True])
def test_only_pinned_data_bytes_change(passive):
    original = module(passive=passive)
    spec = change(original)
    result = patch_wasm(original, [spec])
    assert result == original.replace(b"OLD MARK", b"NEW MARK")
    assert len(result) == len(original)
    assert data_ranges(result) == data_ranges(original)


def test_cannot_modify_non_data_bytes():
    original = module()
    with pytest.raises(ValueError, match="data segment"):
        patch_wasm(original, [change(original, b"CODE", b"NOPE")])


@pytest.mark.parametrize(
    "field,value",
    [
        ("offset", 0),
        ("length", 9),
        ("count", 2),
        ("original_sha256", "0" * 64),
        ("replacement_sha256", "0" * 64),
    ],
)
def test_mismatched_pin_fails_closed(field, value):
    original = module()
    spec = change(original)
    spec[field] = value
    with pytest.raises(ValueError):
        patch_wasm(original, [spec])


def test_overlapping_patches_are_rejected():
    original = module()
    spec = change(original)
    with pytest.raises(ValueError, match="overlap"):
        patch_wasm(original, [spec, spec])


@pytest.mark.parametrize(
    "data",
    [
        b"not wasm",
        module()[:-1],
        b"\x00asm\x01\x00\x00\x00\x0b\xff\xff\xff\xff\xff\xff",
    ],
)
def test_malformed_wasm_is_rejected(data):
    with pytest.raises(ValueError):
        data_ranges(data)


def test_replacement_png_uses_valid_padding_before_iend():
    data = replacement_bytes(
        {"kind": "png-mark", "length": 24715},
        Path(__file__).parents[1] / "assets/branding",
    )
    assert len(data) == 24715 and data.startswith(b"\x89PNG\r\n\x1a\n")
    p = 8
    kinds = []
    compressed = b""
    while p < len(data):
        size = struct.unpack(">I", data[p : p + 4])[0]
        kind = data[p + 4 : p + 8]
        payload = data[p + 8 : p + 8 + size]
        assert (
            zlib.crc32(kind + payload)
            == struct.unpack(">I", data[p + 8 + size : p + 12 + size])[0]
        )
        if kind == b"IDAT":
            compressed += payload
        if kind == b"IHDR":
            assert struct.unpack(">II", payload[:8]) == (64, 64)
        kinds.append(kind)
        p += size + 12
    assert kinds == [b"IHDR", b"IDAT", b"npAD", b"IEND"]
    assert len(zlib.decompress(compressed)) == 64 * (64 * 4 + 1)
    assert p == len(data)


def test_svg_and_path_padding_are_parsable_and_independent():
    import xml.etree.ElementTree as ET

    assets = Path(__file__).parents[1] / "assets/branding"
    svg = replacement_bytes({"kind": "svg-mark", "length": 341}, assets)
    assert len(svg) == 341
    tree = ET.fromstring(svg)
    assert tree.tag.endswith("svg") and b"ArtCraft" not in svg
    path = replacement_bytes({"kind": "path-mark", "length": 169}, assets)
    assert path.strip() == b"M20 0H44V64H100V88H20Z"


def test_bundle_updates_sri_gzip_and_preserves_notices(tmp_path):
    assets = Path(__file__).parents[1] / "assets/branding"
    before = b"OLD MARK".ljust(169, b" ")
    after = replacement_bytes({"kind": "path-mark", "length": 169}, assets)
    original = module(before)
    patch = change(original, before, after)
    changed = patch_wasm(original, [patch])
    old_sri = base64.b64encode(hashlib.sha384(original).digest()).decode()
    html = (
        '<html><head><link href="app.wasm" integrity="sha384-'
        + old_sri
        + '"></head></html>'
    ).encode()
    (tmp_path / "app.wasm").write_bytes(original)
    (tmp_path / "app.wasm.gz").write_bytes(gzip.compress(original))
    (tmp_path / "app.wasm.br").write_bytes(b"obsolete compressed version")
    (tmp_path / "index.html").write_bytes(html)
    (tmp_path / "LICENSE-MIT").write_bytes(b"Original copyright must remain.\r\n")
    spec = {
        "id": "fixture",
        "version": "v1",
        "source_commit": "a" * 40,
        "wasm_file": "app.wasm",
        "original_sha256": hashlib.sha256(original).hexdigest(),
        "modified_sha256": hashlib.sha256(changed).hexdigest(),
        "html_sha256": hashlib.sha256(html).hexdigest(),
        "sri_count": 1,
        "patches": [
            {key: value for key, value in patch.items() if key != "replacement"}
            | {"kind": "path-mark"}
        ],
    }
    result = transform_bundle(tmp_path, spec, assets)
    assert gzip.decompress((tmp_path / "app.wasm.gz").read_bytes()) == changed
    assert not (tmp_path / "app.wasm.br").exists()
    assert (
        "sha384-" + base64.b64encode(hashlib.sha384(changed).digest()).decode()
    ).encode() in (tmp_path / "index.html").read_bytes()
    assert (
        tmp_path / "LICENSE-MIT"
    ).read_bytes() == b"Original copyright must remain.\r\n"
    assert result["original_sha256"] == spec["original_sha256"]
    assert result["modified_sha256"] == spec["modified_sha256"]
    assert json.loads((tmp_path / "LIBERTY-MODIFICATIONS.json").read_text()) == result


def test_wrong_full_binary_hash_does_not_write(tmp_path):
    original = module()
    (tmp_path / "app.wasm").write_bytes(original)
    (tmp_path / "index.html").write_text("<html></html>")
    spec = {"id": "fixture", "wasm_file": "app.wasm", "original_sha256": "0" * 64}
    with pytest.raises(ValueError, match="original SHA-256"):
        transform_bundle(tmp_path, spec, [])
    assert (tmp_path / "app.wasm").read_bytes() == original
    assert not (tmp_path / "LIBERTY-MODIFICATIONS.json").exists()


def test_every_catalog_version_requires_a_branding_review(tmp_path):
    from scripts.brand_apps import apply_branding

    root = Path(__file__).parents[1]
    lock = json.loads((root / "branding.lock.json").read_text())
    catalog = json.loads((root / "upstream.lock.json").read_text())
    assert {
        (a["id"], a["version"]) for a in lock["apps"] + lock["unmodified_apps"]
    } == {(a["id"], a["version"]) for a in catalog["apps"]}
    with pytest.raises(ValueError, match="reviewed branding inventory"):
        apply_branding({"id": "unknown", "version": "v1"}, tmp_path)
    with pytest.raises(
        ValueError, match="version mismatch|reviewed branding inventory"
    ):
        apply_branding({"id": "wordcraft", "version": "v999"}, tmp_path)


def test_all_locked_replacements_match_pinned_hashes_and_lengths():
    import xml.etree.ElementTree as ET

    root = Path(__file__).parents[1]
    lock = json.loads((root / "branding.lock.json").read_text())
    for app in lock["apps"]:
        assert app["original_sha256"] != app["modified_sha256"]
        for patch in app["patches"]:
            data = replacement_bytes(patch, root / "assets/branding")
            assert len(data) == patch["length"]
            assert hashlib.sha256(data).hexdigest() == patch["replacement_sha256"]
            if patch["kind"].startswith("svg-"):
                ET.fromstring(data)


def test_text_label_replacement_is_explicit_and_not_a_global_brand_substitution():
    assets = Path(__file__).parents[1] / "assets/branding"
    patch = {
        "kind": "text-label",
        "length": 35,
        "replacement_text": "Based on original upstream work.",
    }
    result = replacement_bytes(patch, assets)
    assert result == b"Based on original upstream work.".ljust(35, b" ")
    with pytest.raises(ValueError, match="exceeds pinned"):
        replacement_bytes(patch | {"length": 5}, assets)
