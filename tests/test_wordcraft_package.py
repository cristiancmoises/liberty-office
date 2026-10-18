"""Synthetic packaging boundaries; actual native validity is tested separately."""

import gzip
import hashlib
import importlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = "wordcraft-web-8f83828293ff7c4d"


def installed_gzip(data, name):
    output = io.BytesIO()
    with gzip.GzipFile(
        filename=name, fileobj=output, mode="wb", compresslevel=6, mtime=0
    ) as compressed:
        compressed.write(data)
    return output.getvalue()


def fixture(tmp_path):
    source, output, fonts = (tmp_path / name for name in ("source", "out", "fonts"))
    (source / "apps/wordcraft-web").mkdir(parents=True)
    (source / "assets/app-icon").mkdir(parents=True)
    (source / "assets/app-icon/wordcraft.ico").write_bytes(b"synthetic icon")
    (source / "assets/hyphenation").mkdir()
    (source / "assets/hyphenation/pl.pat").write_text("Original MIT pattern notice")
    (source / "apps/wordcraft-web/index.html").write_text(
        '<html><link data-trunk rel="icon" href="../../assets/app-icon/wordcraft.ico" />'
        '<link data-trunk rel="rust" data-bin="wordcraft-web" data-wasm-opt="z" data-weak-refs /></html>'
    )
    output.mkdir()
    (output / (ARTIFACT + ".js")).write_text("export default async function(){}")
    (output / (ARTIFACT + "_bg.wasm")).write_bytes(b"\0asm\1\0\0\0")
    for name in ("LICENSE-MIT", "LICENSE-APACHE", "NOTICE", "ATTRIBUTION.md"):
        (source / name).write_text("Original " + name)
    for name in (
        "LICENSE-MIT",
        "LICENSE-APACHE",
        "ATTRIBUTION.md",
        "fonts/noto-sans-arabic/OFL.txt",
    ):
        path = fonts / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Original fonts " + name)
    return source, output, fonts


def package(paths):
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/package_wordcraft_web.py"),
            *map(str, paths),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_word_build_record_binds_real_files_recipes_and_all_font_notices(tmp_path):
    paths = fixture(tmp_path)
    result = package(paths)
    assert result.returncode == 0, result.stderr
    source, output, _ = paths
    record = json.loads((tmp_path / "out-build.json").read_text())
    assert record["id"] == "wordcraft" and record["version"] == "v0.7.0"
    assert record["cargo_locked"] and record["cargo_profile"] == "release"
    assert record["wasm_bindgen_options"] == "--target web --weak-refs"
    assert record["craft_fonts_commit"] == "8dcdacd5153e64560d109541a47d806f26f048c0"
    assert (
        record["craft_fonts_sha256"]
        == "c0bfca8f4dd8c98825e598c0324c66d90609fe531b212a6c9a04f6852dc5387b"
    )
    assert set(record["files"]) == {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    }
    for name, expected in record["files"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected
    assert (output / "NOTICE").read_bytes() == (source / "NOTICE").read_bytes()
    assert (output / "licenses/wordcraft/assets/hyphenation/pl.pat").read_bytes() == (
        source / "assets/hyphenation/pl.pat"
    ).read_bytes()
    assert (
        (output / "licenses/craft-fonts/fonts/noto-sans-arabic/OFL.txt")
        .read_text()
        .startswith("Original fonts")
    )
    for name in (
        "scripts/patch_wordcraft_web.py",
        "scripts/build_wordcraft_web.sh",
        "scripts/package_wordcraft_web.py",
        "patches/wordcraft-web/save_order_tests.rs",
    ):
        assert (
            record["patch_files"][name]
            == hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        )
    html = (output / "index.html").read_text()
    assert "await init()" in html and "data-trunk" not in html


def test_word_packager_rejects_bad_wasm_before_recording_success(tmp_path):
    paths = fixture(tmp_path)
    (paths[1] / (ARTIFACT + "_bg.wasm")).write_bytes(b"not wasm")
    result = package(paths)
    assert result.returncode != 0 and "WebAssembly" in result.stderr
    assert not (tmp_path / "out-build.json").exists()


def test_word_packager_keeps_deferred_preloads_and_real_compiled_integrity(tmp_path):
    import base64
    from html.parser import HTMLParser

    paths = fixture(tmp_path)
    result = package(paths)
    assert result.returncode == 0, result.stderr
    links = []

    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "link" and values.get("rel") in ("modulepreload", "preload"):
                links.append(values)

    Links().feed((paths[1] / "index.html").read_text())
    expected = []
    for suffix, relation in ((".js", "modulepreload"), ("_bg.wasm", "preload")):
        name = ARTIFACT + suffix
        integrity = base64.b64encode(
            hashlib.sha384((paths[1] / name).read_bytes()).digest()
        ).decode()
        entry = {
            "rel": relation,
            "href": "./" + name,
            "crossorigin": "anonymous",
            "integrity": "sha384-" + integrity,
        }
        if suffix.endswith(".wasm"):
            entry.update({"as": "fetch", "type": "application/wasm"})
        expected.append(entry)
    assert links == expected


@pytest.mark.parametrize("size", [39_785_016, 44_292_364, 48 * 1024**2])
def test_word_budget_accepts_measured_editor_sizes_through_exact_decoded_boundary(
    tmp_path, size
):
    # These sparse synthetic bytes test budgets, not validity of a compiled editor.
    paths = fixture(tmp_path)
    wasm = paths[1] / (ARTIFACT + "_bg.wasm")
    with wasm.open("r+b") as stream:
        stream.truncate(size)
    result = package(paths)
    assert result.returncode == 0, result.stderr
    record = json.loads((tmp_path / "out-build.json").read_text())
    assert record["additional_liberty_wasm_limit_bytes"] == 48 * 1024**2
    assert record["additional_liberty_wasm_gzip_limit_bytes"] == 20 * 1024**2
    assert record["wasm_identity_bytes"] == size
    assert record["wasm_gzip_level"] == 6
    assert record["wasm_gzip_bytes"] == len(
        installed_gzip(wasm.read_bytes(), wasm.name)
    )


@pytest.mark.parametrize("over_budget", [False, True])
def test_word_gzip_transfer_exact_boundary_and_one_byte_over(
    tmp_path, monkeypatch, over_budget
):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("package_wordcraft_web")
    paths = fixture(tmp_path)
    wasm = paths[1] / (ARTIFACT + "_bg.wasm")
    encoded = len(installed_gzip(wasm.read_bytes(), wasm.name))
    # Scale the policy boundary down to exercise exact bytes without random
    # multi-megabyte fixtures; the default20MiB budget is asserted above.
    monkeypatch.setattr(module, "MAX_WASM_GZIP_BYTES", encoded - int(over_budget))
    if over_budget:
        with pytest.raises(ValueError, match="gzip transfer"):
            module.package(*paths)
        assert not (tmp_path / "out-build.json").exists()
    else:
        module.package(*paths)
        record = json.loads((tmp_path / "out-build.json").read_text())
        assert record["wasm_gzip_bytes"] == encoded


@pytest.mark.parametrize(
    "problem", ["oversized", "symlink", "root-symlink", "duplicate-entrypoint"]
)
def test_word_packager_rejects_unsafe_or_unexpected_output(tmp_path, problem):
    paths = fixture(tmp_path)
    source, output, _ = paths
    if problem == "oversized":
        with (output / (ARTIFACT + "_bg.wasm")).open("r+b") as stream:
            stream.truncate(48 * 1024**2 + 1)
    elif problem == "symlink":
        (output / "extra.js").symlink_to(output / (ARTIFACT + ".js"))
    elif problem == "root-symlink":
        target = output.with_name("actual-output")
        output.rename(target)
        output.symlink_to(target, target_is_directory=True)
    else:
        html = source / "apps/wordcraft-web/index.html"
        html.write_text(html.read_text() + '<link data-trunk rel="rust">')
    result = package(paths)
    assert result.returncode != 0
    expected = {
        "oversized": "48 MiB",
        "symlink": "Symlinks",
        "root-symlink": "Symlinks",
        "duplicate-entrypoint": "exactly one",
    }[problem]
    assert expected in result.stderr
    assert not (tmp_path / "out-build.json").exists()
