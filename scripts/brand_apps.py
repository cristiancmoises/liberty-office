#!/usr/bin/env python3
"""Replace reviewed graphics in pinned WASM data only; preserve executable sections.

This is an offline installation transform, not a runtime memory patch. The separate
lock pins original and resulting files. Unknown inputs fail closed. Legal notices,
source credits and independently licensed application icons are not rewritten.
"""

import argparse
import base64
import gzip
import hashlib
import json
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _leb(data, offset, end):
    value = 0
    for shift in range(0, 35, 7):
        if offset >= end:
            raise ValueError("Truncated WASM LEB128")
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            if shift == 28 and byte & 0x70:
                raise ValueError("Oversized WASM LEB128")
            return value, offset
    raise ValueError("Invalid WASM LEB128")


def data_ranges(data):
    """Return only raw data payload spans, never headers, offsets or instructions.

    Accept the active i32.const and passive segments used by the pinned releases;
    unfamiliar constant expressions fail closed instead of guessing boundaries.
    """
    if data[:8] != b"\x00asm\x01\x00\x00\x00":
        raise ValueError("Invalid WASM header")
    offset = 8
    ranges = []
    seen = False
    while offset < len(data):
        section = data[offset]
        size, start = _leb(data, offset + 1, len(data))
        end = start + size
        if end > len(data):
            raise ValueError("Truncated WASM section")
        if section == 11:
            if seen:
                raise ValueError("Duplicate WASM data section")
            seen = True
            count, position = _leb(data, start, end)
            for _ in range(count):
                flags, position = _leb(data, position, end)
                if flags == 2:
                    _, position = _leb(data, position, end)
                if flags in (0, 2):
                    if position >= end or data[position] != 0x41:
                        raise ValueError("Unsupported WASM data offset expression")
                    # These pinned wasm32 binaries use non-negative i32 offsets.
                    _, position = _leb(data, position + 1, end)
                    if position >= end or data[position] != 0x0B:
                        raise ValueError("Unsupported WASM data offset expression")
                    position += 1
                elif flags != 1:
                    raise ValueError("Unsupported WASM data segment flags")
                length, position = _leb(data, position, end)
                if position + length > end:
                    raise ValueError("Truncated WASM data payload")
                ranges.append((position, position + length))
                position += length
            if position != end:
                raise ValueError("Unexpected bytes after WASM data segments")
        offset = end
    return ranges


def patch_wasm(original, patches):
    ranges = data_ranges(original)
    modified = bytearray(original)
    previous_end = -1
    for patch in sorted(patches, key=lambda item: item["offset"]):
        start, length = patch["offset"], patch["length"]
        end = start + length
        if start < previous_end:
            raise ValueError("WASM patches overlap")
        if length <= 0 or not any(a <= start and end <= b for a, b in ranges):
            raise ValueError("Patch is not wholly inside a WASM data segment")
        before = original[start:end]
        after = patch["replacement"]
        if (
            sha256(before) != patch["original_sha256"]
            or original.count(before) != patch["count"]
        ):
            raise ValueError("Original graphics hash/count mismatch")
        if len(after) != length or sha256(after) != patch["replacement_sha256"]:
            raise ValueError("Replacement graphics size/hash mismatch")
        modified[start:end] = after
        previous_end = end
    return bytes(modified)


def _rectangles(assets, wordmark):
    geometry = json.loads((assets / "geometry.json").read_text())
    rectangles: list[tuple[tuple[int, ...], tuple[int, int, int, int] | None]] = [
        (tuple(rect), (103, 229, 237, 255)) for rect in geometry["mark_rectangles"]
    ]
    if wordmark:
        for index, letter in enumerate("LIBERTY"):
            for y, row in enumerate(geometry["letters"][letter]):
                for x, pixel in enumerate(row):
                    if pixel == "1":
                        rectangles.append(
                            ((72 + index * 42 + x * 6, 11 + y * 6, 6, 6), None)
                        )
    return rectangles


def _chunk(kind, payload):
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload))
    )


def replacement_bytes(patch, assets):
    assets = Path(assets)
    kind, length = patch["kind"], patch["length"]
    if kind == "path-mark":
        result = (assets / "mark.path").read_bytes().strip()
    elif kind == "text-label":
        result = patch["replacement_text"].encode("utf-8")
    elif kind == "svg-mark":
        result = (assets / "mark.svg").read_bytes().strip()
    elif kind.startswith(("png-", "svg-wordmark-")):
        wordmark = "wordmark" in kind
        white = kind.endswith("-white")
        ink = (240, 246, 248, 255) if white else (24, 39, 48, 255)
        width, height = (366, 64) if wordmark else (64, 64)
        rectangles = _rectangles(assets, wordmark)
        if kind.startswith("svg-"):
            paths = {}
            for (x, y, w, h), colour in rectangles:
                colour = colour or ink
                paths.setdefault(colour, []).append(f"M{x} {y}h{w}v{h}h-{w}z")
            shapes = "".join(
                f'<path fill="#{c[0]:02x}{c[1]:02x}{c[2]:02x}" d="{"".join(d)}"/>'
                for c, d in paths.items()
            )
            result = (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">'
                + shapes
                + "</svg>"
            ).encode()
        else:
            pixels = bytearray(width * height * 4)
            for (x, y, w, h), colour in rectangles:
                if not 0 <= x < x + w <= width or not 0 <= y < y + h <= height:
                    raise ValueError("Branding geometry exceeds image bounds")
                for row in range(y, y + h):
                    start = (row * width + x) * 4
                    pixels[start : start + w * 4] = bytes(colour or ink) * w
            raw = b"".join(
                b"\x00" + pixels[y * width * 4 : (y + 1) * width * 4]
                for y in range(height)
            )
            result = b"\x89PNG\r\n\x1a\n" + _chunk(
                b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
            )
            result += _chunk(b"IDAT", zlib.compress(raw, 9))
            # A valid private ancillary chunk pads BEFORE IEND. No trailing garbage.
            padding = length - len(result) - 24
            if padding < 0:
                raise ValueError("Replacement PNG exceeds pinned payload size")
            return result + _chunk(b"npAD", b"\x00" * padding) + _chunk(b"IEND", b"")
    else:
        raise ValueError("Unknown branding replacement kind")
    if len(result) > length:
        raise ValueError("Replacement exceeds pinned payload size")
    return result.ljust(length, b" ")


def transform_bundle(bundle, spec, assets):
    bundle = Path(bundle)
    filename = spec["wasm_file"]
    if Path(filename).name != filename:
        raise ValueError("Unsafe WASM filename")
    wasm_path = bundle / filename
    original = wasm_path.read_bytes()
    if sha256(original) != spec["original_sha256"]:
        raise ValueError("WASM original SHA-256 mismatch")
    html_path = bundle / "index.html"
    html = html_path.read_bytes()
    if sha256(html) != spec["html_sha256"]:
        raise ValueError("Original HTML SHA-256 mismatch")
    patches = [
        patch | {"replacement": replacement_bytes(patch, assets)}
        for patch in spec["patches"]
    ]
    modified = patch_wasm(original, patches)
    if sha256(modified) != spec["modified_sha256"]:
        raise ValueError("WASM modified SHA-256 mismatch")
    old_sri = b"sha384-" + base64.b64encode(hashlib.sha384(original).digest())
    new_sri = b"sha384-" + base64.b64encode(hashlib.sha384(modified).digest())
    if html.count(old_sri) != spec["sri_count"]:
        raise ValueError("Unexpected WASM SRI count")
    updated_html = html.replace(old_sri, new_sri)
    updated_html += b"\n<!-- Liberty integration: restricted graphics replaced; see LIBERTY-MODIFICATIONS.json. Not an official upstream build. -->\n"
    removed = [
        name + ".br"
        for name in (filename, "index.html")
        if (bundle / (name + ".br")).is_file()
    ]
    record = {
        key: spec[key]
        for key in (
            "id",
            "version",
            "source_commit",
            "original_sha256",
            "modified_sha256",
        )
    }
    record.update(
        {
            "notice": "Modified by Liberty Office: independent graphics replace restricted marks and selected runtime identity labels identify this integration as based on upstream. Not an official upstream build. Original code instructions, legal notices and upstream attribution are preserved.",
            "wasm_file": filename,
            "original_html_sha256": sha256(html),
            "modified_html_sha256": sha256(updated_html),
            "patches": [
                {key: value for key, value in patch.items() if key != "replacement"}
                for patch in patches
            ],
            "removed_stale_brotli": removed,
        }
    )
    # All checks happen before any artifact is written. The caller installs a disposable stage.
    wasm_path.write_bytes(modified)
    (bundle / (filename + ".gz")).write_bytes(
        gzip.compress(modified, compresslevel=6, mtime=0)
    )
    html_path.write_bytes(updated_html)
    if (bundle / "index.html.gz").is_file():
        (bundle / "index.html.gz").write_bytes(
            gzip.compress(updated_html, compresslevel=6, mtime=0)
        )
    for name in removed:
        (bundle / name).unlink()
    (bundle / "LIBERTY-MODIFICATIONS.json").write_text(
        json.dumps(record, indent=2) + "\n"
    )
    installed = bundle / "installed.json"
    if installed.is_file():
        metadata = json.loads(installed.read_text())
        metadata["branding"] = record
        for name in removed:
            metadata["files"].pop(name, None)
        for name in (
            filename,
            filename + ".gz",
            "index.html",
            "index.html.gz",
            "LIBERTY-MODIFICATIONS.json",
        ):
            if (bundle / name).is_file():
                metadata["files"][name] = sha256((bundle / name).read_bytes())
        installed.write_text(json.dumps(metadata, indent=2) + "\n")
    return record


def apply_branding(app, bundle, lock=ROOT / "branding.lock.json"):
    inventory = json.loads(Path(lock).read_text())
    spec = next(
        (entry for entry in inventory["apps"] if entry["id"] == app["id"]), None
    )
    if spec is None:
        reviewed = next(
            (
                entry
                for entry in inventory["unmodified_apps"]
                if entry["id"] == app["id"]
            ),
            None,
        )
        if reviewed is None or reviewed["version"] != app["version"]:
            raise ValueError(
                "No reviewed branding inventory for this application version"
            )
        return None
    if app["version"] != spec["version"]:
        raise ValueError("Branding inventory version mismatch")
    return transform_bundle(bundle, spec, ROOT / "assets/branding")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apps", type=Path, required=True)
    args = parser.parse_args()
    inventory = json.loads((ROOT / "branding.lock.json").read_text())
    for spec in inventory["apps"]:
        transform_bundle(args.apps / spec["id"], spec, ROOT / "assets/branding")
        print(spec["id"] + ": pinned data-only branding transformation verified")


if __name__ == "__main__":
    main()
