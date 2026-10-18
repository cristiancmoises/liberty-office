"""Closed public-code inventory and independently verifiable generations.

This module is stdlib-only so native packaging and stateless delivery do not
need a private database or application service.
"""

import gzip
import hashlib
import json
import mimetypes
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

PROJECT = Path(__file__).resolve().parents[1]
REVIEWED = json.loads((PROJECT / "public-assets.lock.json").read_text())["apps"]
SUFFIXES = {"identity": "", "gzip": ".gz", "br": ".br"}
HASH = re.compile("[0-9a-f]{64}")


def _canonical(value: dict) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _file(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if (
        not relative.parts
        or relative.is_absolute()
        or str(relative) != name
        or any(part.startswith(".") for part in relative.parts)
        or "\\" in name
        or ":" in name
    ):
        raise ValueError("Unsafe public asset path")
    path = root / name
    if root.is_symlink() or any(
        parent.is_symlink()
        for parent in [path, *path.parents]
        if parent == root or root in parent.parents
    ):
        raise ValueError("Public assets cannot use symlinks")
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Missing public asset")
    return path


def _mime(name: str) -> str:
    return (
        "application/wasm"
        if name.endswith(".wasm")
        else mimetypes.guess_type(name)[0] or "application/octet-stream"
    )


def _retain_generations(previous: Path, output: Path) -> None:
    """Import only manifest-selected bytes from an operator-verified old image."""
    previous = Path(previous)
    if previous.is_symlink() or not previous.is_dir():
        raise ValueError("Expected a regular previous public store")
    if output.resolve().is_relative_to(
        previous.resolve()
    ) or previous.resolve().is_relative_to(output.resolve()):
        raise ValueError("Previous and new public stores must be separate")
    if not any(previous.iterdir()):
        return  # The explicit empty-image stage supports first installations.
    registry = load_public_generations(previous)
    if {path.name for path in previous.iterdir()} != {
        "current",
        *registry["generations"],
    }:
        raise ValueError("Unexpected previous public-store entry")
    for generation, manifest in registry["generations"].items():
        final = output / generation
        if final.exists():
            if load_public_manifest(final / "manifest.json") != manifest:
                raise ValueError("Retained generation differs from its verified input")
            continue
        with tempfile.TemporaryDirectory(prefix=".retain-", dir=output) as temporary:
            stage = Path(temporary) / generation
            stage.mkdir()
            names = ["manifest.json"]
            for app_id, files in manifest["apps"].items():
                for name, entry in files.items():
                    names.extend(
                        app_id + "/" + name + SUFFIXES[encoding]
                        for encoding in entry["representations"]
                    )
            for name in names:
                destination = stage / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(_file(previous / generation, name), destination)
            load_public_manifest(stage / "manifest.json")
            stage.rename(final)


def build_public_manifest(
    apps_dir: Path, output: Path, *, previous: Path | None = None
) -> dict:
    """Copy reviewed verified code into a new generation; retain older ones."""
    apps_dir, output = Path(apps_dir), Path(output)
    if apps_dir.is_symlink() or output.is_symlink():
        raise ValueError("Asset roots cannot use symlinks")
    versions = {
        app["id"]: app["version"]
        for app in json.loads((PROJECT / "upstream.lock.json").read_text())["apps"]
    }
    apps, sources = {}, {}
    for app_id, names in REVIEWED.items():
        root = apps_dir / app_id
        if not root.exists() and not root.is_symlink():
            continue
        record = json.loads(_file(apps_dir, app_id + "/installed.json").read_text())
        if (
            record.get("id") != app_id
            or record.get("version") != versions[app_id]
            or not isinstance(record.get("files"), dict)
        ):
            raise ValueError("Unverified editor installation")
        files = {}
        for name in names:
            path = _file(root, name)
            digest, size = _digest(path), path.stat().st_size
            if not size or digest != record["files"].get(name):
                raise ValueError("Public asset differs from verified installation")
            variants = {"identity": {"sha256": digest, "size": size}}
            sources[app_id + "/" + name] = path
            for encoding, suffix in [("gzip", ".gz"), ("br", ".br")]:
                candidate = root / (name + suffix)
                if not candidate.exists() and not candidate.is_symlink():
                    continue
                candidate = _file(root, name + suffix)
                actual = _digest(candidate)
                recorded = record["files"].get(name + suffix)
                if recorded is not None and actual != recorded:
                    raise ValueError(
                        "Compressed public asset differs from verified installation"
                    )
                if encoding == "gzip":
                    decoded, total = hashlib.sha256(), 0
                    with gzip.open(candidate, "rb") as stream:
                        while chunk := stream.read(1024 * 1024):
                            total += len(chunk)
                            if total > size:
                                raise ValueError(
                                    "Compressed asset exceeds verified decoded size"
                                )
                            decoded.update(chunk)
                    if total != size or decoded.hexdigest() != digest:
                        raise ValueError(
                            "Compressed asset does not decode to verified code"
                        )
                elif recorded is None:
                    raise ValueError("Brotli requires a verified compressed digest")
                variants[encoding] = {
                    "sha256": actual,
                    "size": candidate.stat().st_size,
                }
                sources[app_id + "/" + name + suffix] = candidate
            files[name] = {"mime": _mime(name), "representations": variants}
        apps[app_id] = files
    if not apps:
        raise ValueError("No verified public assets")
    payload = {"schema": 1, "apps": apps}
    generation = hashlib.sha256(_canonical(payload)).hexdigest()
    manifest = payload | {"generation": generation}
    output.mkdir(parents=True, exist_ok=True)
    if previous is not None:
        _retain_generations(previous, output)
    with tempfile.TemporaryDirectory(prefix=".build-", dir=output) as temporary:
        stage = Path(temporary) / "generation"
        stage.mkdir()
        for name, source in sources.items():
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        (stage / "manifest.json").write_bytes(_canonical(manifest) + b"\n")
        final = output / generation
        if final.exists():
            if load_public_manifest(final / "manifest.json") != manifest:
                raise ValueError("Generation already exists with different bytes")
        else:
            stage.rename(final)
        current = Path(temporary) / "current"
        current.write_text(generation + "\n")
        current.replace(output / "current")
    return manifest


def load_public_manifest(path: Path) -> dict:
    """Reject altered manifests, unknown paths and mismatched payload bytes."""
    path = Path(path)
    if path.name != "manifest.json":
        raise ValueError("Expected a public manifest path")
    root, store = path.parent, path.parent.parent
    manifest = json.loads(_file(store, root.name + "/manifest.json").read_text())
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema", "generation", "apps"}
        or manifest["schema"] != 1
        or manifest["generation"] != root.name
        or not HASH.fullmatch(root.name)
        or not isinstance(manifest["apps"], dict)
        or not manifest["apps"]
    ):
        raise ValueError("Invalid public manifest")
    payload = {"schema": 1, "apps": manifest["apps"]}
    if hashlib.sha256(_canonical(payload)).hexdigest() != root.name:
        raise ValueError("Public generation hash mismatch")
    for app_id, files in manifest["apps"].items():
        if (
            app_id not in REVIEWED
            or not isinstance(files, dict)
            or set(files) != set(REVIEWED[app_id])
        ):
            raise ValueError("Public manifest contains unreviewed paths")
        for name, entry in files.items():
            if (
                not isinstance(entry, dict)
                or set(entry) != {"mime", "representations"}
                or entry["mime"] != _mime(name)
            ):
                raise ValueError("Invalid public asset metadata")
            variants = entry["representations"]
            if (
                not isinstance(variants, dict)
                or "identity" not in variants
                or not variants.keys() <= SUFFIXES.keys()
            ):
                raise ValueError("Invalid public representations")
            for encoding, metadata in variants.items():
                if (
                    not isinstance(metadata, dict)
                    or set(metadata) != {"sha256", "size"}
                    or not isinstance(metadata["sha256"], str)
                    or not HASH.fullmatch(metadata["sha256"])
                    or type(metadata["size"]) is not int
                    or metadata["size"] <= 0
                ):
                    raise ValueError("Invalid public representation digest")
                file = _file(root, app_id + "/" + name + SUFFIXES[encoding])
                if (
                    file.stat().st_size != metadata["size"]
                    or _digest(file) != metadata["sha256"]
                ):
                    raise ValueError("Public representation hash mismatch")
    return manifest


def load_public_generations(root: Path) -> dict:
    root = Path(root)
    current = _file(root, "current").read_text().strip()
    generations = {
        path.name: load_public_manifest(path / "manifest.json")
        for path in root.iterdir()
        if HASH.fullmatch(path.name)
    }
    if current not in generations:
        raise ValueError("Current public generation is missing")
    return {"root": root, "current": current, "generations": generations}
