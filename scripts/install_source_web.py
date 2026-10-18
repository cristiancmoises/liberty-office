"""Install reviewed source-built editors; preserve original notices."""

import argparse
import gzip
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

SOURCE_BUILD_VERSIONS = {
    "figcraft": "v0.6.0",
    "gridcraft": "v0.7.0",
    "wordcraft": "v0.7.0",
}


def supported_identity(spec):
    app_id = spec.get("id")
    return (
        isinstance(app_id, str)
        and app_id in SOURCE_BUILD_VERSIONS
        and (spec.get("version") == SOURCE_BUILD_VERSIONS[app_id])
    )


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_build_matches(record, lock):
    """Check installed provenance and asset digests against the public build lock."""
    lock = Path(lock)
    spec = json.loads(lock.read_text())
    if not supported_identity(spec):
        return False
    expected = {
        "source_commit": spec["source_commit"],
        "source_sha256": spec["source_sha256"],
        "lock_sha256": digest(lock),
    }
    files = record.get("files")
    return (
        record.get("id") == spec["id"]
        and record.get("version") == spec["version"]
        and record.get("source_build") == expected
        and isinstance(files, dict)
        and all(files.get(name) == value for name, value in spec["files"].items())
    )


def install(bundle, output, lock):
    bundle, output, lock = Path(bundle), Path(output), Path(lock)
    spec = json.loads(lock.read_text())
    if (
        not supported_identity(spec)
        or not re.fullmatch(r"[0-9a-f]{40}", spec.get("source_commit", ""))
        or not re.fullmatch(r"[0-9a-f]{64}", spec.get("source_sha256", ""))
    ):
        raise ValueError("Unexpected editor source-build identity")
    app_id = spec["id"]
    patches = spec.get("patch_files")
    if not isinstance(patches, dict) or not 1 <= len(patches) <= 32:
        raise ValueError("Missing reviewed editor build inputs")
    for name, expected in patches.items():
        relative = PurePosixPath(name)
        path = lock.parent / relative
        if (
            not relative.parts
            or relative.is_absolute()
            or ".." in relative.parts
            or str(relative) != name
            or "\\" in name
            or ":" in name
            or not path.resolve().is_relative_to(lock.parent.resolve())
            or path.is_symlink()
            or not path.is_file()
            or digest(path) != expected
        ):
            raise ValueError(
                "Editor patch/build recipe differs from the reviewed inputs"
            )
    files = spec.get("files")
    if not isinstance(files, dict) or not 3 <= len(files) <= 1000:
        raise ValueError("Invalid editor build inventory")
    for name, expected in files.items():
        path = PurePosixPath(name)
        if (
            not path.parts
            or path.is_absolute()
            or ".." in path.parts
            or str(path) != name
            or "\\" in name
            or ":" in name
            or not isinstance(expected, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected)
        ):
            raise ValueError("Unsafe editor build inventory entry")
    entries = list(bundle.rglob("*"))
    if any(path.is_symlink() for path in entries):
        raise ValueError("Symlinks are not accepted in editor builds")
    actual = {
        path.relative_to(bundle).as_posix(): path for path in entries if path.is_file()
    }
    if actual.keys() != files.keys() or "index.html" not in actual:
        raise ValueError("Editor build files differ from the reviewed inventory")
    if not any(name.endswith(".wasm") for name in files) or not any(
        name.endswith(".js") for name in files
    ):
        raise ValueError("Editor build lacks WebAssembly or JavaScript")
    if sum(path.stat().st_size for path in actual.values()) > 1024**3:
        raise ValueError("Editor build exceeds the installation limit")
    if any(digest(path) != files[name] for name, path in actual.items()):
        raise ValueError("Editor build SHA-256 mismatch")
    target = output / app_id
    if not target.is_dir() or target.is_symlink():
        raise ValueError("A verified original editor installation is required")
    original_entries = list(target.rglob("*"))
    if any(path.is_symlink() for path in original_entries):
        raise ValueError("Unexpected symlink in the original editor installation")
    provenance = {
        "source_commit": spec["source_commit"],
        "source_sha256": spec["source_sha256"],
        "lock_sha256": digest(lock),
    }
    # All validation precedes replacement. Only this generated editor bundle is touched.
    with tempfile.TemporaryDirectory(
        prefix=f"prepare-{app_id}-", dir=output
    ) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        for name, path in actual.items():
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
        for path in original_entries:
            relative = path.relative_to(target)
            notice = path.name.upper().startswith(
                ("LICENSE", "NOTICE", "COPYING", "ATTRIBUTION", "AUTHORS", "ASSETS")
            )
            notice = notice or any(
                part.lower() in ("licenses", "notices") for part in relative.parts
            )
            if not path.is_file() or not notice:
                continue
            destination = stage / relative
            if destination.exists() and digest(destination) != digest(path):
                raise ValueError(
                    "Source build would overwrite an original editor notice"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
        if any(digest(stage / name) != expected for name, expected in files.items()):
            raise ValueError("Staged editor build SHA-256 mismatch")
        modifications = {
            "id": app_id,
            "kind": "source-build",
            **provenance,
            "changes": [
                "Reviewed source patches identified by the pinned build lock",
                "Neutral product identity with original source attribution",
            ],
            "editor_patch_license": "MIT OR Apache-2.0",
        }
        (stage / "LIBERTY-MODIFICATIONS.json").write_text(
            json.dumps(modifications, indent=2) + "\n"
        )
        for path in list(stage.rglob("*")):
            if path.suffix in (".wasm", ".js"):
                with (
                    path.open("rb") as source,
                    path.with_name(path.name + ".gz").open("wb") as destination,
                    gzip.GzipFile(
                        fileobj=destination, mode="wb", compresslevel=6, mtime=0
                    ) as compressed,
                ):
                    shutil.copyfileobj(source, compressed, 1024 * 1024)
        record = {
            "id": app_id,
            "version": spec["version"],
            "source_build": provenance,
            "files": {
                path.relative_to(stage).as_posix(): digest(path)
                for path in stage.rglob("*")
                if path.is_file()
            },
        }
        (stage / "installed.json").write_text(json.dumps(record, indent=2) + "\n")
        # A rollback failure must not put the original inside automatic cleanup.
        backup = Path(tempfile.mkdtemp(prefix=f"{app_id}-original-", dir=output))
        previous = backup / "original"
        try:
            target.rename(previous)
        except BaseException:
            backup.rmdir()
            raise
        try:
            stage.rename(target)
        except BaseException:
            try:
                previous.rename(target)
            except BaseException as error:
                error.add_note(
                    "Original editor bundle retained for recovery at " + str(previous)
                )
                raise
            backup.rmdir()
            raise
        shutil.rmtree(backup)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    args = parser.parse_args()
    install(args.bundle, args.output, args.lock)
    print("Verified source-built editor installed; original notices preserved.")
