#!/usr/bin/env python3
"""Package generated FigCraft glue with upstream HTML/licenses and a build record."""

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

from patch_figcraft_web import SOURCE_COMMIT, SOURCE_SHA256, replace_once


def package(source, output, fonts):
    glue = output / "figcraft-web.js"
    if not glue.is_file() or not glue.stat().st_size:
        raise ValueError("Missing generated JavaScript entrypoint")
    wasm = output / "figcraft-web_bg.wasm"
    if not wasm.is_file() or wasm.read_bytes()[:4] != b"\0asm":
        raise ValueError("Missing real compiled WebAssembly output")
    if wasm.stat().st_size > 24 * 1024 * 1024:
        raise ValueError(
            "Compiled WebAssembly exceeds the upstream 24 MiB package gate"
        )
    html = (source / "apps/figcraft-web/index.html").read_text()
    links = re.findall(r'<link data-trunk rel="rust"[^>]*>', html)
    if len(links) != 1:
        raise ValueError("Expected exactly one original Rust entrypoint")
    html = replace_once(
        html,
        links[0],
        '<script type="module">import init from "./figcraft-web.js"; await init();</script>',
    )
    (output / "index.html").write_text(html)
    for name in ("LICENSE-MIT", "LICENSE-APACHE", "NOTICE"):
        shutil.copyfile(source / name, output / name)
    for source_name, output_name in (
        ("fonts/inter/OFL.txt", "CRAFT-FONTS-INTER-OFL.txt"),
        ("ATTRIBUTION.md", "CRAFT-FONTS-ATTRIBUTION.md"),
        ("LICENSE-MIT", "CRAFT-FONTS-LICENSE-MIT"),
        ("LICENSE-APACHE", "CRAFT-FONTS-LICENSE-APACHE"),
    ):
        shutil.copyfile(fonts / source_name, output / output_name)
    repository = Path(__file__).resolve().parent.parent
    patches = [
        repository / "scripts/patch_figcraft_web.py",
        repository / "scripts/build_figcraft_web.sh",
        repository / "scripts/package_figcraft_web.py",
        *sorted((repository / "patches/figcraft-web").glob("*.rs")),
    ]
    record = {
        "schema": 1,
        "id": "figcraft",
        "version": "v0.6.0",
        "source_commit": SOURCE_COMMIT,
        "source_sha256": SOURCE_SHA256,
        "source_archive_sha256": SOURCE_SHA256,
        "license": "MIT OR Apache-2.0",
        "rust_image": "rust:1.95.0-bookworm@sha256:6258907abe69656e41cd992e0b705cdcfabcbbe3db374f92ed2d47121282d4a1",
        "wasm_bindgen": "0.2.129",
        "binaryen_version": "133",
        "binaryen_archive_sha256": "2dc9c7813f5375db93d96ead4b78222fcc3e2677bbb832297af4797782a37489",
        "wasm_opt": "-Oz --enable-bulk-memory --enable-bulk-memory-opt --enable-nontrapping-float-to-int --enable-sign-ext --enable-reference-types --enable-multivalue",
        "craft_fonts_commit": "43913056ce82a3fdad0ef69f6b88d1dc922a8104",
        "craft_fonts_sha256": "e2dd2bb3ae39e442ee67416b9bc29b7ca8ef906e8ff2caaf5a451aaa6c662057",
        "cargo_locked": True,
        "cargo_profile": "web-release",
        "build_work_directory": str(source.resolve().parent),
        "cargo_profile_overrides": {"lto": "thin"},
        "source_date_epoch": 1791936000,
        "modifications": "Bounded browser file I/O using original project/image encoders; two reviewed runtime identity labels. Copyrights and source credits preserved.",
        "patch_files": {
            str(p.relative_to(repository)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in patches
        },
        "files": {
            p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.rglob("*"))
            if p.is_file()
        },
    }
    output.with_name(output.name + "-build.json").write_text(
        json.dumps(record, indent=2) + "\n"
    )


if __name__ == "__main__":
    package(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
