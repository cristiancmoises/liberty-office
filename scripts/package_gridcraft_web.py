#!/usr/bin/env python3
"""Package compiled GridCraft assets, original notices and exact build provenance."""

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

from patch_gridcraft_web import SOURCE_COMMIT, SOURCE_SHA256, replace_once


def package(source, output, fonts):
    glue = output / "gridcraft-web.js"
    if not glue.is_file() or not glue.stat().st_size:
        raise ValueError("Missing generated JavaScript entrypoint")
    wasm = output / "gridcraft-web_bg.wasm"
    if not wasm.is_file():
        raise ValueError("Missing real compiled WebAssembly output")
    if wasm.stat().st_size > 24 * 1024 * 1024:
        raise ValueError(
            "Compiled WebAssembly exceeds the additional Liberty 24 MiB gate"
        )
    with wasm.open("rb") as stream:
        if stream.read(4) != b"\0asm":
            raise ValueError("Missing real compiled WebAssembly output")
    html = (source / "apps/gridcraft-web/index.html").read_text()
    links = re.findall(r'<link data-trunk rel="rust"[^>]*>', html)
    if len(links) != 1:
        raise ValueError("Expected exactly one original Rust entrypoint")
    html = replace_once(
        html,
        links[0],
        '<script type="module">import init from "./gridcraft-web.js"; await init();</script>',
    )
    html = replace_once(
        html,
        '<link data-trunk rel="icon" href="../../assets/app-icon/gridcraft.ico" />',
        '<link rel="icon" href="./gridcraft.ico" />',
    )
    (output / "index.html").write_text(html)
    shutil.copyfile(source / "assets/app-icon/gridcraft.ico", output / "gridcraft.ico")
    for name in ("LICENSE-MIT", "LICENSE-APACHE", "NOTICE"):
        shutil.copyfile(source / name, output / name)
    for name in ("ATTRIBUTION.md", "LICENSE-MIT", "LICENSE-APACHE"):
        shutil.copyfile(fonts / name, output / ("CRAFT-FONTS-" + name))
    for family in ("biz-ud-mincho", "biz-ud-pgothic", "shippori-mincho"):
        shutil.copyfile(
            fonts / "fonts" / family / "OFL.txt",
            output / ("CRAFT-FONTS-" + family.upper() + "-OFL.txt"),
        )
    repository = Path(__file__).resolve().parent.parent
    patches = [
        repository / "scripts/patch_gridcraft_web.py",
        repository / "scripts/build_gridcraft_web.sh",
        repository / "scripts/package_gridcraft_web.py",
        *sorted(
            path
            for path in (repository / "patches/gridcraft-web").iterdir()
            if path.suffix in {".rs", ".toml", ".py"}
        ),
    ]
    record = {
        "schema": 1,
        "id": "gridcraft",
        "version": "v0.7.0",
        "source_commit": SOURCE_COMMIT,
        "source_sha256": SOURCE_SHA256,
        "source_archive_sha256": SOURCE_SHA256,
        "license": "MIT OR Apache-2.0",
        "rust_image": "rust:1.95.0-bookworm@sha256:6258907abe69656e41cd992e0b705cdcfabcbbe3db374f92ed2d47121282d4a1",
        "wasm_bindgen": "0.2.129",
        "wasm_bindgen_options": "--target web --weak-refs",
        "binaryen_version": "133",
        "binaryen_archive_sha256": "2dc9c7813f5375db93d96ead4b78222fcc3e2677bbb832297af4797782a37489",
        "wasm_opt": "-Oz --enable-bulk-memory --enable-bulk-memory-opt --enable-nontrapping-float-to-int --enable-sign-ext --enable-reference-types --enable-multivalue",
        "craft_fonts_commit": "abb83316d96aa59c1cf64784289e378fe9fa5695",
        "craft_fonts_sha256": "53e41ed01ee81a0ef664601a73fb87281f1fd748e724f560c8128d7d33eb3328",
        "cargo_locked": True,
        "cargo_profile": "release",
        "build_work_directory": str(source.resolve().parent),
        "cargo_profile_overrides": {"lto": "thin"},
        "source_date_epoch": 1791936000,
        "additional_liberty_wasm_limit_bytes": 24 * 1024 * 1024,
        "modifications": "Exact-once initial text/focus handoff and ordered keyboard edit boundaries; one reviewed runtime identity label. Original engine, fonts, copyright and source credits preserved.",
        "patch_files": {
            str(path.relative_to(repository)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in patches
        },
        "files": {
            path.relative_to(output).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
    }
    output.with_name(output.name + "-build.json").write_text(
        json.dumps(record, indent=2) + "\n"
    )


if __name__ == "__main__":
    package(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
