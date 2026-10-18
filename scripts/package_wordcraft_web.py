#!/usr/bin/env python3
"""Package native WordCraft output with original notices and build provenance."""

import base64
import gzip
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

from patch_wordcraft_web import SOURCE_COMMIT, SOURCE_SHA256

# WordCraft's measured installed baseline is 39,785,016 bytes. Keep separate
# decoded and gzip-transfer budgets; these are Liberty bounds, not upstream CI.
MAX_WASM_BYTES = 48 * 1024 * 1024
MAX_WASM_GZIP_BYTES = 20 * 1024 * 1024
# Retain reviewed basenames so older immutable generations remain loadable.
# The generation SHA-256, not this historical Trunk suffix, identifies the bytes.
ARTIFACT = "wordcraft-web-8f83828293ff7c4d"


def gzip_size(path):
    class Counter:
        size = 0

        def write(self, data):
            self.size += len(data)
            return len(data)

        def flush(self):
            pass

    counter = Counter()
    # Match install_source_web's gzip6/mtime0 and original basename header.
    with (
        path.open("rb") as source,
        gzip.GzipFile(
            filename=path.name, fileobj=counter, mode="wb", compresslevel=6, mtime=0
        ) as compressed,
    ):
        shutil.copyfileobj(source, compressed, 1024 * 1024)
    return counter.size


def package(source, output, fonts):
    if output.is_symlink() or any(path.is_symlink() for path in output.rglob("*")):
        raise ValueError("Symlinks are not accepted in compiled output")
    glue, wasm = (output / (ARTIFACT + suffix) for suffix in (".js", "_bg.wasm"))
    if not glue.is_file() or not glue.stat().st_size:
        raise ValueError("Missing generated JavaScript entrypoint")
    if not wasm.is_file() or wasm.stat().st_size > MAX_WASM_BYTES:
        raise ValueError(
            "Missing WebAssembly or additional Liberty 48 MiB decoded limit exceeded"
        )
    with wasm.open("rb") as stream:
        if stream.read(4) != b"\0asm":
            raise ValueError("Missing real compiled WebAssembly output")
    gzip_bytes = gzip_size(wasm)
    if gzip_bytes > MAX_WASM_GZIP_BYTES:
        raise ValueError("Additional Liberty 20 MiB gzip transfer limit exceeded")
    html = (source / "apps/wordcraft-web/index.html").read_text()
    links = re.findall(r'<link data-trunk rel="rust"[^>]*>', html)
    if len(links) != 1:
        raise ValueError("Expected exactly one original Rust entrypoint")
    preloads = []
    for path, relation, attributes in (
        (glue, "modulepreload", ""),
        (wasm, "preload", ' as="fetch" type="application/wasm"'),
    ):
        integrity = base64.b64encode(
            hashlib.sha384(path.read_bytes()).digest()
        ).decode()
        preloads.append(
            f'<link rel="{relation}" href="./{path.name}" crossorigin="anonymous"'
            f' integrity="sha384-{integrity}"{attributes} />'
        )
    html = html.replace(
        links[0],
        "\n".join(preloads)
        + f'\n<script type="module">import init from "./{ARTIFACT}.js"; await init();</script>',
        1,
    )
    icon = '<link data-trunk rel="icon" href="../../assets/app-icon/wordcraft.ico" />'
    if html.count(icon) != 1:
        raise ValueError("Unexpected original WordCraft icon entrypoint")
    (output / "index.html").write_text(
        html.replace(icon, '<link rel="icon" href="./wordcraft.ico" />', 1)
    )
    shutil.copyfile(source / "assets/app-icon/wordcraft.ico", output / "wordcraft.ico")
    for name in ("LICENSE-MIT", "LICENSE-APACHE", "NOTICE", "ATTRIBUTION.md"):
        shutil.copyfile(source / name, output / name)
    # Preserve every bundled font notice, not just the families used by older builds.
    notices = [
        (fonts / name, Path(name))
        for name in ("LICENSE-MIT", "LICENSE-APACHE", "ATTRIBUTION.md")
    ]
    notices.extend(
        (path, path.relative_to(fonts))
        for path in fonts.rglob("OFL*.txt")
        if path.is_file()
    )
    for path, relative in notices:
        destination = output / "licenses/craft-fonts" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    for path in (source / "assets").rglob("*"):
        if path.is_file() and (
            path.name.upper().startswith(
                ("OFL", "LICENSE", "NOTICE", "COPYING", "ATTRIBUTION")
            )
            or (path.parent.name == "hyphenation" and path.suffix == ".pat")
        ):
            destination = output / "licenses/wordcraft" / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    repository = Path(__file__).resolve().parents[1]
    patches = [
        repository / "scripts" / name
        for name in (
            "patch_wordcraft_web.py",
            "build_wordcraft_web.sh",
            "package_wordcraft_web.py",
        )
    ]
    patches.extend(sorted((repository / "patches/wordcraft-web").glob("*.rs")))
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    record = {
        "schema": 1,
        "id": "wordcraft",
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
        "craft_fonts_commit": "8dcdacd5153e64560d109541a47d806f26f048c0",
        "craft_fonts_sha256": "c0bfca8f4dd8c98825e598c0324c66d90609fe531b212a6c9a04f6852dc5387b",
        "cargo_locked": True,
        "cargo_profile": "release",
        "cargo_profile_overrides": {},
        "source_date_epoch": 1791936000,
        "additional_liberty_wasm_limit_bytes": MAX_WASM_BYTES,
        "additional_liberty_wasm_gzip_limit_bytes": MAX_WASM_GZIP_BYTES,
        "wasm_identity_bytes": wasm.stat().st_size,
        "wasm_gzip_bytes": gzip_bytes,
        "wasm_gzip_level": 6,
        "artifact_basename": ARTIFACT,
        "modifications": "Process admitted text events in FIFO order before later save shortcuts, including equation text. Retain the first text when document focus returns from ribbon/status chrome without stealing widget, popup or modal focus. Original empty/control-character filters and Alt shortcut suppression retained. Identify the independent Liberty integration. Copyright, source credits, licensed application icon, pattern notices and fonts preserved; restricted brand images are not bundled.",
        "patch_files": {
            str(path.relative_to(repository)): digest(path) for path in patches
        },
        "files": {
            path.relative_to(output).as_posix(): digest(path)
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
    }
    output.with_name(output.name + "-build.json").write_text(
        json.dumps(record, indent=2) + "\n"
    )


if __name__ == "__main__":
    package(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
