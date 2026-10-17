"""Build-record tests use synthetic headers, not a claim of compiled app validity."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fixture(tmp_path):
    source, output, fonts = (tmp_path / name for name in ("source", "out", "fonts"))
    (source / "apps/figcraft-web").mkdir(parents=True)
    (fonts / "fonts/inter").mkdir(parents=True)
    output.mkdir()
    (source / "apps/figcraft-web/index.html").write_text(
        '<html><link data-trunk rel="rust" data-wasm-opt="z"></html>'
    )
    for name in ("LICENSE-MIT", "LICENSE-APACHE", "NOTICE"):
        (source / name).write_text("Original " + name)
    for name in (
        "LICENSE-MIT",
        "LICENSE-APACHE",
        "ATTRIBUTION.md",
        "fonts/inter/OFL.txt",
    ):
        (fonts / name).write_text("Font attribution " + name)
    (output / "figcraft-web_bg.wasm").write_bytes(b"\0asm\1\0\0\0")
    (output / "figcraft-web.js").write_text("export default async function(){}")
    return source, output, fonts


def run_package(paths):
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/package_figcraft_web.py"),
            *map(str, paths),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_build_record_binds_assets_recipe_and_preserves_licenses(tmp_path):
    paths = fixture(tmp_path)
    (paths[1] / "snippets").mkdir()
    (paths[1] / "snippets/helper.js").write_text("export {}")
    result = run_package(paths)
    assert result.returncode == 0, result.stderr
    source, output, _ = paths
    record = json.loads((tmp_path / "out-build.json").read_text())
    assert record["cargo_profile_overrides"] == {"lto": "thin"}
    assert set(record["files"]) == {
        p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()
    }
    for name, digest in record["files"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    for name in (
        "scripts/build_figcraft_web.sh",
        "scripts/package_figcraft_web.py",
        "scripts/patch_figcraft_web.py",
    ):
        assert (
            record["patch_files"][name]
            == hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        )
    assert (output / "NOTICE").read_bytes() == (source / "NOTICE").read_bytes()
    assert (
        (output / "CRAFT-FONTS-INTER-OFL.txt")
        .read_text()
        .startswith("Font attribution")
    )
    assert "await init()" in (output / "index.html").read_text()


def test_package_rejects_missing_or_non_wasm_output(tmp_path):
    paths = fixture(tmp_path)
    (paths[1] / "figcraft-web_bg.wasm").write_bytes(b"not wasm")
    result = run_package(paths)
    assert result.returncode != 0
    assert "Missing real compiled WebAssembly output" in result.stderr
    assert not (tmp_path / "out-build.json").exists()


def test_package_keeps_upstream_size_gate(tmp_path):
    paths = fixture(tmp_path)
    with (paths[1] / "figcraft-web_bg.wasm").open("r+b") as stream:
        stream.truncate(24 * 1024 * 1024 + 1)
    result = run_package(paths)
    assert result.returncode != 0
    assert "24 MiB" in result.stderr
    assert not (tmp_path / "out-build.json").exists()
