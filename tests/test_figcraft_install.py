import hashlib
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.install_source_web import install


@pytest.fixture(params=["figcraft", "gridcraft"])
def app_id(request):
    return request.param


def fixture(tmp_path, app_id):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    files = {
        "index.html": b"<html></html>",
        "fig.js": b"export {}",
        "fig.wasm": b"\0asm\1\0\0\0",
    }
    for name, data in files.items():
        (bundle / name).write_bytes(data)
    spec = {
        "id": app_id,
        "version": {"figcraft": "v0.6.0", "gridcraft": "v0.7.0"}[app_id],
        "source_commit": "a" * 40,
        "source_sha256": "b" * 64,
        "files": {
            name: hashlib.sha256(data).hexdigest() for name, data in files.items()
        },
        "patch_files": {"patch.py": hashlib.sha256(b"reviewed patch").hexdigest()},
    }
    (tmp_path / "patch.py").write_bytes(b"reviewed patch")
    lock = tmp_path / "build.lock.json"
    lock.write_text(json.dumps(spec))
    output = tmp_path / "apps"
    target = output / app_id
    target.mkdir(parents=True)
    (target / "LICENSE-MIT").write_bytes(b"Original license\r\n")
    (target / "stale.wasm").write_bytes(b"old")
    (output / "other-editor").mkdir()
    (output / "other-editor" / "index.html").write_bytes(b"untouched")
    return bundle, lock, output, spec


def test_installs_only_verified_editor_and_preserves_original_notices(tmp_path, app_id):
    bundle, lock, output, spec = fixture(tmp_path, app_id)
    record = install(bundle, output, lock)
    target = output / app_id
    assert (target / "fig.wasm").read_bytes() == b"\0asm\1\0\0\0"
    assert not (target / "stale.wasm").exists()
    assert (target / "LICENSE-MIT").read_bytes() == b"Original license\r\n"
    assert (output / "other-editor" / "index.html").read_bytes() == b"untouched"
    assert record["source_build"]["source_commit"] == spec["source_commit"]
    assert (
        record["source_build"]["lock_sha256"]
        == hashlib.sha256(lock.read_bytes()).hexdigest()
    )
    assert (
        record["files"]["LICENSE-MIT"]
        == hashlib.sha256(b"Original license\r\n").hexdigest()
    )
    assert (
        json.loads((target / "LIBERTY-MODIFICATIONS.json").read_text())["kind"]
        == "source-build"
    )


def test_runtime_diagnostics_require_the_reviewed_build_and_asset_hashes(
    tmp_path, app_id
):
    from scripts.install_source_web import source_build_matches

    bundle, lock, output, _ = fixture(tmp_path, app_id)
    record = install(bundle, output, lock)
    assert source_build_matches(record, lock)
    wrong_source = json.loads(json.dumps(record))
    wrong_source["source_build"]["source_sha256"] = "0" * 64
    assert not source_build_matches(wrong_source, lock)
    wrong_files = json.loads(json.dumps(record))
    wrong_files["files"]["fig.wasm"] = "0" * 64
    assert not source_build_matches(wrong_files, lock)
    assert not source_build_matches({}, lock)


@pytest.mark.parametrize(
    "problem",
    [
        "tampered",
        "extra",
        "missing",
        "traversal",
        "symlink",
        "wrong-app",
        "changed-patch",
        "unsafe-patch",
    ],
)
def test_invalid_source_build_never_changes_installed_bundle(tmp_path, problem, app_id):
    bundle, lock, output, spec = fixture(tmp_path, app_id)
    if problem == "tampered":
        (bundle / "fig.wasm").write_bytes(b"wrong")
    elif problem == "extra":
        (bundle / "unexpected.js").write_bytes(b"wrong")
    elif problem == "missing":
        (bundle / "fig.js").unlink()
    elif problem == "traversal":
        spec["files"]["../outside"] = "c" * 64
        lock.write_text(json.dumps(spec))
    elif problem == "symlink":
        (bundle / "fig.js").unlink()
        (bundle / "fig.js").symlink_to(bundle / "index.html")
    elif problem == "changed-patch":
        (tmp_path / "patch.py").write_bytes(b"stale compiled output")
    elif problem == "unsafe-patch":
        spec["patch_files"] = {"../outside": "d" * 64}
        lock.write_text(json.dumps(spec))
    else:
        spec["id"] = "other-editor"
        lock.write_text(json.dumps(spec))
    before = {
        str(path.relative_to(output)): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    with pytest.raises(ValueError):
        install(bundle, output, lock)
    assert before == {
        str(path.relative_to(output)): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }


def test_failed_replacement_and_rollback_retain_original_for_recovery(tmp_path, app_id):
    bundle, lock, output, _ = fixture(tmp_path, app_id)
    target = output / app_id
    original_rename = Path.rename
    failed_restores = []

    def fail_rename_to_target(source, destination):
        if Path(destination) == target:
            failed_restores.append(source)
            raise OSError("injected destination rename failure")
        return original_rename(source, destination)

    with (
        patch.object(Path, "rename", fail_rename_to_target),
        pytest.raises(OSError, match="injected destination rename failure"),
    ):
        install(bundle, output, lock)
    assert len(failed_restores) == 2
    # A failed rollback must leave the complete original outside disposable staging.
    retained = list(output.rglob("LICENSE-MIT"))
    assert len(retained) == 1
    assert retained[0].read_bytes() == b"Original license\r\n"
    assert (retained[0].parent / "stale.wasm").read_bytes() == b"old"
    assert (output / "other-editor" / "index.html").read_bytes() == b"untouched"


def test_source_mutation_during_copy_is_rejected_before_replacement(tmp_path, app_id):
    bundle, lock, output, _ = fixture(tmp_path, app_id)
    original_copy = shutil.copyfile
    before = {
        str(path.relative_to(output)): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }

    def mutate_before_copy(source, destination, *args, **kwargs):
        if source == bundle / "fig.js":
            source.write_bytes(b"changed after validation")
        return original_copy(source, destination, *args, **kwargs)

    with (
        patch.object(shutil, "copyfile", mutate_before_copy),
        pytest.raises(ValueError, match="SHA-256"),
    ):
        install(bundle, output, lock)
    assert before == {
        str(path.relative_to(output)): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }


def test_conflicting_original_notice_never_replaces_installed_editor(tmp_path, app_id):
    bundle, lock, output, spec = fixture(tmp_path, app_id)
    (bundle / "LICENSE-MIT").write_bytes(b"Changed license")
    spec["files"]["LICENSE-MIT"] = hashlib.sha256(b"Changed license").hexdigest()
    lock.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="original .* notice"):
        install(bundle, output, lock)
    assert (output / app_id / "LICENSE-MIT").read_bytes() == b"Original license\r\n"
    assert (output / app_id / "stale.wasm").read_bytes() == b"old"


def test_other_editor_or_unreviewed_version_never_matches_runtime_record(
    tmp_path, app_id
):
    from scripts.install_source_web import source_build_matches

    bundle, lock, output, spec = fixture(tmp_path, app_id)
    record = install(bundle, output, lock)
    other = "gridcraft" if app_id == "figcraft" else "figcraft"
    wrong_editor = {**record, "id": other}
    assert not source_build_matches(wrong_editor, lock)
    spec["version"] = "v99.0.0"
    lock.write_text(json.dumps(spec))
    record["version"] = spec["version"]
    record["source_build"]["lock_sha256"] = hashlib.sha256(
        lock.read_bytes()
    ).hexdigest()
    assert not source_build_matches(record, lock)
    with pytest.raises(ValueError, match="identity"):
        install(bundle, output, lock)
