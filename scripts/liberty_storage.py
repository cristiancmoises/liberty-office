"""Guarded Liberty storage admission and offline authoritative reconciliation."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Self
from uuid import UUID

GIB = 1073741824


def _validate_identity(expected: dict) -> None:
    identity_keys = {
        "pve",
        "ct",
        "ct_hostname",
        "init_pid",
        "init_start_ticks",
        "blue_container",
        "blue_image",
        "vg_uuid",
        "root_lv_uuid",
    }
    uuid_pattern = r"[A-Za-z0-9]{6}(?:-[A-Za-z0-9]{4}){5}-[A-Za-z0-9]{6}"
    if (
        set(expected) != identity_keys
        or expected.get("ct_hostname") != "office-suite.lab"
        or any(
            type(expected.get(key)) is not int or expected[key] <= 1
            for key in ("init_pid", "init_start_ticks")
        )
        or not isinstance(expected.get("blue_container"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", expected["blue_container"])
        or not isinstance(expected.get("blue_image"), str)
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", expected["blue_image"])
        or any(
            not isinstance(expected.get(key), str)
            or not re.fullmatch(uuid_pattern, expected[key])
            for key in ("vg_uuid", "root_lv_uuid")
        )
    ):
        raise ValueError(
            "Storage requires exact process/container/image/LVM identities"
        )
    if (
        expected.get("pve") != "securityops"
        or type(expected.get("ct")) is not int
        or expected.get("ct") != 154
    ):
        raise ValueError("This adapter is scoped to the Liberty host and CT154")


def storage_preflight(facts: dict, expected: dict) -> dict:
    """No I/O or provisioning: reject drift and low floors before creating an LV."""
    _validate_identity(expected)
    if facts.get("identity") != expected:
        raise ValueError(
            "Host, CT, process, container, image or device identity changed"
        )
    for key in (
        "source_bytes",
        "ram_available",
        "pve_root_free",
        "ct_root_free",
        "vg_free",
        "backup_free",
    ):
        if type(facts.get(key)) is not int or facts[key] < 0:
            raise ValueError("Expected nonnegative integer capacity measurements")
    floors = {
        "ram_available": 4 * GIB,
        "pve_root_free": 8 * GIB,
        "ct_root_free": 5 * GIB,
        "vg_free": 60 * GIB,
        "backup_free": 2 * facts["source_bytes"] + GIB,
    }
    if any(facts[key] < floor for key, floor in floors.items()):
        raise ValueError("A storage or memory safety floor is not met")
    for key in ("thin_data_percent", "thin_metadata_percent"):
        value = facts.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 <= value < 80
        ):
            raise ValueError(
                "Thin-pool data and metadata must each remain below 80 percent"
            )
    if (
        facts.get("existing_data_lv") is not False
        or facts.get("device_signatures") != []
        or facts.get("mp1") is not None
        or facts.get("pending") != []
        or facts.get("active_tasks") != []
        or facts.get("ct_lock") is not None
        or facts.get("hotplug_supported") is not True
    ):
        raise ValueError(
            "Existing device, occupied mount, lock, task or pending/restart state"
        )
    if (
        facts.get("uid_map") != [0, 100000, 65536]
        or facts.get("gid_map") != [0, 100000, 65536]
        or facts.get("app_uid") != 10001
        or facts.get("app_gid") != 10001
    ):
        raise ValueError(
            "The application UID/GID mapping differs from the qualified layout"
        )
    return {
        "lv": "pve/liberty-ct154-data",
        "bytes": 50 * GIB,
        "mp": "mp1",
        "ct_path": "/srv/liberty-data-next",
        "global_quota": 45 * GIB,
        "min_free_bytes": GIB,
        "host_uid": 110001,
        "host_gid": 110001,
    }


def _regular(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Private storage requires regular, non-linked files")


def _safe_source(data: Path) -> None:
    if data.is_symlink() or not data.is_dir():
        raise ValueError("Expected the existing private data directory")
    for name in ("liberty.db", "mfa.key"):
        _regular(data / name)
    for name in ("server.lock", "bootstrap-token", "liberty.db-wal", "liberty.db-shm"):
        path = data / name
        if path.exists() or path.is_symlink():
            _regular(path)
    blobs = data / "blobs"
    if blobs.is_symlink() or not blobs.is_dir():
        raise ValueError("Expected the existing non-linked blob directory")
    for path in blobs.iterdir():
        _regular(path)


def _checkpoint(data: Path) -> None:
    with closing(sqlite3.connect(data / "liberty.db")) as connection:
        status = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if status[0] != 0:
            raise ValueError(
                "Database checkpoint did not finish under offline ownership"
            )


def _inventory(data: Path) -> dict:
    from liberty.cli import file_hash

    _safe_source(data)
    names = ["liberty.db", "mfa.key"]
    if (data / "bootstrap-token").exists():
        names.append("bootstrap-token")
    with closing(
        sqlite3.connect((data / "liberty.db").as_uri() + "?mode=ro", uri=True)
    ) as connection:
        if connection.execute("PRAGMA user_version").fetchone()[0] != 2:
            raise ValueError("Expected the qualified schema-2 database")
        for blob, size, digest in connection.execute(
            "SELECT id,size,sha256 FROM versions"
        ):
            if (
                not re.fullmatch(r"[a-f0-9]{32}", blob)
                or type(size) is not int
                or size < 0
                or not re.fullmatch(r"[a-f0-9]{64}", digest)
            ):
                raise ValueError("Invalid referenced blob metadata")
            path = data / "blobs" / blob
            _regular(path)
            if path.stat().st_size != size or file_hash(path) != digest:
                raise ValueError("Referenced blob content differs from the database")
            names.append("blobs/" + blob)
    return {
        name: {"size": (data / name).stat().st_size, "sha256": file_hash(data / name)}
        for name in sorted(names)
    }


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_snapshot(data: Path, names: dict) -> None:
    """Flush restored files before their containing directory entries."""
    directories = {data, data / "blobs"}
    for name in names:
        path = data / name
        _regular(path)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        directories.add(path.parent)
    for directory in sorted(
        directories, key=lambda path: len(path.parts), reverse=True
    ):
        _sync_directory(directory)


def offline_snapshot(source: Path, destination: Path, backup: Path) -> dict:
    """Retain a protected backup and preserve the current sessions during migration.

    Reuse the normal backup lock/validation. Reacquire source ownership, checkpoint
    and compare its full inventory before restoring, holding that lease throughout
    reconciliation. A writer in the reacquisition gap causes an abort, not a stale
    restore. The caller must separately prove actual old-process exit.
    """
    from liberty.cli import file_hash, make_backup, offline, restore_backup

    source, destination, backup = Path(source), Path(destination), Path(backup)
    if (
        destination.is_symlink()
        or not destination.is_dir()
        or any(destination.iterdir())
        or source.resolve().is_relative_to(destination.resolve())
        or destination.resolve().is_relative_to(source.resolve())
        or backup.resolve().is_relative_to(source.resolve())
        or backup.resolve().is_relative_to(destination.resolve())
    ):
        raise ValueError(
            "Expected separate source, empty destination and protected backup"
        )
    # Validate references before the existing archiver can read a blob path.
    # The second lease still detects any change made in the reacquisition gaps.
    _safe_source(source)
    with offline(source):
        _checkpoint(source)
        _inventory(source)
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        manifest = make_backup(source, stream)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(backup.parent)
    with offline(source):
        _checkpoint(source)
        if _inventory(source) != manifest["files"]:
            raise ValueError(
                "Authoritative data changed after the snapshot; do not restore it"
            )
        restore_backup(backup, destination, preserve_sessions=True)
        if _inventory(destination) != manifest["files"]:
            raise ValueError(
                "Reconciled inventory differs from the authoritative snapshot"
            )
        _sync_snapshot(destination, manifest["files"])
    return {
        "verified": True,
        "files": len(manifest["files"]),
        "bytes": sum(item["size"] for item in manifest["files"].values()),
        "database_sha256": manifest["files"]["liberty.db"]["sha256"],
        "backup_sha256": file_hash(backup),
    }


def protect_public_accounts(data: Path) -> int:
    """Protect every public marker before an uninstrumented old writer starts."""
    from liberty.cli import offline

    data = Path(data)
    _safe_source(data)
    with offline(data), closing(sqlite3.connect(data / "liberty.db")) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='public_accounts'"
        ).fetchone():
            connection.rollback()
            return 0
        try:
            count = connection.execute(
                "UPDATE public_accounts SET cleanup_protected=1"
            ).rowcount
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            raise
        _checkpoint(data)
        return count


class ProvisionOps(Protocol):
    def measure(self) -> dict: ...
    def record(self, event: str, receipt: dict | None = None) -> None: ...
    def create_lv(self, plan: dict) -> object: ...
    def inspect_new_lv(self) -> dict: ...
    def format_new_lv(self, lv: dict) -> dict: ...
    def mount_and_attach(self, filesystem: dict) -> dict: ...


def provision_storage(
    ops: ProvisionOps, expected: dict, *, apply: bool = False
) -> dict:
    """Only a newly created, tagged, unsigned LV may reach the formatter.

    Failures preserve the journal and exact newly allocated objects. There is no
    automatic wipe, detach, restart, deletion or retry of an uncertain operation.
    """
    plan = storage_preflight(ops.measure(), expected)
    if apply is not True:
        return {"applied": False, "plan": plan}
    ops.record("lv-create.started", plan)
    ops.create_lv(plan)
    lv = ops.inspect_new_lv()
    if (
        lv.get("name") != plan["lv"]
        or lv.get("bytes") != plan["bytes"]
        or lv.get("vg_uuid") != expected["vg_uuid"]
        or lv.get("uuid") == expected["root_lv_uuid"]
        or not isinstance(lv.get("uuid"), str)
        or not re.fullmatch(
            r"[A-Za-z0-9]{6}(?:-[A-Za-z0-9]{4}){5}-[A-Za-z0-9]{6}", lv["uuid"]
        )
        or lv.get("tags") != ["liberty_office_data"]
        or lv.get("signatures") != []
    ):
        raise ValueError(
            "Refuse to format an existing, wrong, untagged or signed device"
        )
    ops.record(
        "lv-create.complete",
        {key: lv[key] for key in ("name", "uuid", "bytes", "vg_uuid")},
    )
    ops.record("filesystem.started")
    filesystem = ops.format_new_lv(lv)
    if (
        filesystem.get("type") != "ext4"
        or filesystem.get("lv_uuid") != lv["uuid"]
        or not isinstance(filesystem.get("uuid"), str)
        or str(UUID(filesystem["uuid"])) != filesystem["uuid"]
    ):
        raise ValueError("The new filesystem identity is not qualified")
    ops.record(
        "filesystem.complete",
        {key: filesystem[key] for key in ("uuid", "type", "lv_uuid")},
    )
    ops.record("attach.started")
    mounted = ops.mount_and_attach(filesystem)
    if (
        mounted.get("fs_uuid") != filesystem["uuid"]
        or mounted.get("mp") != plan["mp"]
        or mounted.get("ct_path") != plan["ct_path"]
        or mounted.get("pending") != []
        or mounted.get("restart_required") is not False
        or mounted.get("init_pid") != expected["init_pid"]
        or mounted.get("init_start_ticks") != expected["init_start_ticks"]
        or mounted.get("writable_uid") != 10001
        or type(mounted.get("free_bytes")) is not int
        or mounted["free_bytes"] < 46 * GIB
    ):
        raise ValueError(
            "Hotplug, unchanged CT identity, ownership or capacity is not proven"
        )
    ops.record(
        "attach.complete",
        {
            key: mounted[key]
            for key in (
                "fs_uuid",
                "mp",
                "ct_path",
                "init_pid",
                "init_start_ticks",
                "writable_uid",
                "free_bytes",
                "restart_required",
            )
        },
    )
    ops.record("provision.complete")
    return {
        "applied": True,
        "plan": plan,
        "mount_verified": True,
        "lv_uuid": lv["uuid"],
        "fs_uuid": filesystem["uuid"],
    }


class StorageJournal:
    """Create-once private phase evidence, never document or credential content."""

    EVENTS = frozenset(
        (
            "lv-create.started",
            "lv-create.complete",
            "filesystem.started",
            "filesystem.complete",
            "attach.started",
            "attach.complete",
            "provision.complete",
        )
    )
    FIELDS = frozenset(
        (
            "lv",
            "bytes",
            "mp",
            "ct_path",
            "global_quota",
            "min_free_bytes",
            "host_uid",
            "host_gid",
            "name",
            "uuid",
            "vg_uuid",
            "type",
            "lv_uuid",
            "fs_uuid",
            "init_pid",
            "init_start_ticks",
            "writable_uid",
            "free_bytes",
            "restart_required",
        )
    )

    def __init__(self, path: Path, config_sha256: str):
        if not re.fullmatch(r"[a-f0-9]{64}", config_sha256):
            raise ValueError("Expected the exact private configuration hash")
        self.path = Path(path)
        fd = os.open(
            self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        self.stream = os.fdopen(fd, "w", encoding="utf-8")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._append({"schema": 1, "config_sha256": config_sha256})
            parent = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        except BaseException:
            self.stream.close()
            raise

    def _append(self, value: dict) -> None:
        self.stream.write(json.dumps(value, sort_keys=True) + "\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def record(self, event: str, receipt: dict | None = None) -> None:
        receipt = {} if receipt is None else receipt
        if (
            event not in self.EVENTS
            or not set(receipt) <= self.FIELDS
            or any(type(value) not in (str, int, bool) for value in receipt.values())
            or len(json.dumps(receipt)) > 4096
        ):
            raise ValueError(
                "Only bounded identity/capacity evidence belongs in the storage journal"
            )
        self._append(
            {
                "event": event,
                "receipt": receipt,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.stream.close()


class PrivateStorageConfigError(ValueError):
    """A private operator configuration was not provided."""


def load_storage_config(path: Path) -> tuple[dict, str]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
        ):
            raise PrivateStorageConfigError("A private configuration is required")
        raw = stream.read(32769)
    if len(raw) > 32768:
        raise PrivateStorageConfigError("Private configuration is too large")
    config = json.loads(raw)
    if (
        not isinstance(config, dict)
        or set(config) != {"schema", "run_id", "identity"}
        or config["schema"] != 1
        or not isinstance(config["identity"], dict)
        or not isinstance(config["run_id"], str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9-]{7,63}", config["run_id"])
    ):
        raise PrivateStorageConfigError("Invalid private configuration schema")
    _validate_identity(config["identity"])
    return config, hashlib.sha256(raw).hexdigest()


def storage_mount_unit(fs_uuid: str) -> str:
    if str(UUID(fs_uuid)) != fs_uuid:
        raise ValueError("Expected the exact new filesystem UUID")
    return f"""[Unit]
Description=Liberty CT154 private data
Before=pve-guests.service
JobTimeoutSec=45s

[Mount]
What=/dev/disk/by-uuid/{fs_uuid}
Where=/srv/liberty-data-ct154
Type=ext4
Options=nodev,nosuid,noexec,noatime
DirectoryMode=0700
TimeoutSec=30s

[Install]
WantedBy=multi-user.target
"""


def verify_mount_identity(host: dict, ct: dict, fs_uuid: str, device: str) -> None:
    """CTs may hide UUIDs; require the host UUID and identical kernel device."""
    if (
        not re.fullmatch(r"[0-9]+:[0-9]+", device)
        or host.get("uuid") != fs_uuid
        or ct.get("uuid") not in (None, fs_uuid)
        or host.get("maj:min") != device
        or ct.get("maj:min") != device
        or host.get("target") != "/srv/liberty-data-ct154"
        or ct.get("target") != "/srv/liberty-data-next"
        or any(
            value.get("fstype") != "ext4"
            or not {"nodev", "nosuid", "noexec"}
            <= set(str(value.get("options", "")).split(","))
            for value in (host, ct)
        )
    ):
        raise ValueError("The live host/CT mount and kernel device identities differ")


class PveStorageOps:
    """Host-local, fixed-target adapter; never accepts arbitrary device paths."""

    HOST_MOUNT = Path("/srv/liberty-data-ct154")
    CT_MOUNT = "/srv/liberty-data-next"
    UNIT = r"srv-liberty\x2ddata\x2dct154.mount"
    VOLUME = "/var/lib/docker/volumes/liberty_office_data/_data"

    def __init__(self, expected: dict, journal: StorageJournal | None = None):
        _validate_identity(expected)
        self.expected = expected
        self.journal = journal
        self.created = False
        self.lv: dict | None = None

    @staticmethod
    def command(*argv: str, mutation: bool = False) -> str:
        result = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
            timeout=None if mutation else 30,
            check=False,
        )
        if result.returncode or len(result.stdout) > 2 * 1024 * 1024:
            raise ValueError("A storage command failed; retain the journal and inspect")
        return result.stdout.decode("utf-8").strip()

    def ct(self, *argv: str, mutation: bool = False) -> str:
        return self.command("pct", "exec", "154", "--", *argv, mutation=mutation)

    def _pending(self) -> list:
        values = json.loads(
            self.command(
                "pvesh",
                "get",
                "/nodes/securityops/lxc/154/pending",
                "--output-format",
                "json",
            )
        )
        if not isinstance(values, list):
            raise TypeError("Expected the Proxmox pending-state array")
        return [value for value in values if "pending" in value or value.get("delete")]

    def _config(self) -> dict:
        return dict(
            line.split(": ", 1)
            for line in self.command("pct", "config", "154").splitlines()
            if ": " in line
        )

    def _lvs(self) -> list[dict]:
        report = json.loads(
            self.command(
                "lvs",
                "--reportformat",
                "json",
                "--units",
                "b",
                "--nosuffix",
                "-o",
                "vg_name,lv_name,lv_uuid,lv_size,lv_attr,data_percent,metadata_percent,lv_tags,segtype,lv_kernel_major,lv_kernel_minor",
            )
        )
        return report["report"][0]["lv"]

    def _vg(self) -> dict:
        return json.loads(
            self.command(
                "vgs",
                "pve",
                "--reportformat",
                "json",
                "--units",
                "b",
                "--nosuffix",
                "-o",
                "vg_name,vg_free,vg_uuid",
            )
        )["report"][0]["vg"][0]

    def _process(self) -> tuple[int, int]:
        pid = int(self.command("lxc-info", "-n", "154", "-pH"))
        ticks = int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])
        return pid, ticks

    def _identity(self, config: dict, rows: list[dict]) -> dict:
        if os.geteuid() != 0 or self.command("hostname") != "securityops":
            raise ValueError("This command must run as root on the pinned Proxmox host")
        if config.get("rootfs", "").split(",")[0] != "local-lvm:vm-154-disk-0":
            raise ValueError("Unexpected CT root device")
        fqdn = self.ct("hostname", "-f")
        if config.get("hostname") not in (fqdn, fqdn.split(".")[0]):
            raise ValueError("CT hostname configuration and running FQDN differ")
        pid, ticks = self._process()
        live = json.loads(
            self.ct(
                "docker",
                "inspect",
                "--format",
                '{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},"restarts":{{json .RestartCount}}}',
                self.expected["blue_container"],
            )
        )
        if live["running"] is not True or live["restarts"] != 0:
            raise ValueError(
                "The original writer is not the unchanged running container"
            )
        root = next(
            row
            for row in rows
            if row["vg_name"] == "pve" and row["lv_name"] == "vm-154-disk-0"
        )
        return {
            "pve": "securityops",
            "ct": 154,
            "ct_hostname": fqdn,
            "init_pid": pid,
            "init_start_ticks": ticks,
            "blue_container": live["id"],
            "blue_image": live["image"],
            "vg_uuid": self._vg()["vg_uuid"],
            "root_lv_uuid": root["lv_uuid"],
        }

    def measure(self) -> dict:
        unit = Path("/etc/systemd/system") / self.UNIT
        if (
            self.HOST_MOUNT.exists()
            or self.HOST_MOUNT.is_symlink()
            or unit.exists()
            or unit.is_symlink()
        ):
            raise ValueError("The intended new host mount or unit already exists")
        config, rows = self._config(), self._lvs()
        identity = self._identity(config, rows)
        pid = identity["init_pid"]
        uid_map = [
            int(word) for word in Path(f"/proc/{pid}/uid_map").read_text().split()
        ]
        gid_map = [
            int(word) for word in Path(f"/proc/{pid}/gid_map").read_text().split()
        ]
        tasks = json.loads(
            self.command(
                "pvesh",
                "get",
                "/nodes/securityops/tasks",
                "--source",
                "active",
                "--limit",
                "1000",
                "--output-format",
                "json",
            )
        )
        if not isinstance(tasks, list) or len(tasks) >= 1000:
            raise ValueError("Active task coverage is incomplete")
        available = next(
            int(line.split()[1]) * 1024
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith("MemAvailable:")
        )
        sizes = [
            int(self.ct("du", "--summarize", option, "--", self.VOLUME).split()[0])
            for option in ("--block-size=1", "--bytes")
        ]
        pool = next(
            row for row in rows if row["vg_name"] == "pve" and row["lv_name"] == "data"
        )
        app_uid, app_gid = self.application_ids()
        free = lambda path: os.statvfs(path).f_bavail * os.statvfs(path).f_frsize
        return {
            "identity": identity,
            "ram_available": available,
            "pve_root_free": free("/"),
            "backup_free": free("/var/lib"),
            "ct_root_free": int(
                self.ct(
                    "python3",
                    "-c",
                    "import os;s=os.statvfs('/');print(s.f_bavail*s.f_frsize)",
                )
            ),
            "vg_free": int(self._vg()["vg_free"]),
            "source_bytes": max(sizes),
            "thin_data_percent": float(pool["data_percent"]),
            "thin_metadata_percent": float(pool["metadata_percent"]),
            "existing_data_lv": any(
                row["vg_name"] == "pve" and row["lv_name"] == "liberty-ct154-data"
                for row in rows
            ),
            "device_signatures": [],
            "mp1": config.get("mp1"),
            "pending": self._pending(),
            "active_tasks": tasks,
            "ct_lock": config.get("lock"),
            "uid_map": uid_map,
            "gid_map": gid_map,
            "app_uid": app_uid,
            "app_gid": app_gid,
            "hotplug_supported": "sub mountpoint_hotplug"
            in Path("/usr/share/perl5/PVE/LXC.pm").read_text(),
        }

    def application_ids(self) -> tuple[int, int]:
        # A container's own `id` may conceal a second user-namespace mapping.
        code = "import json,pathlib,subprocess,sys;pid=int(subprocess.check_output(['docker','inspect','--format','{{.State.Pid}}',sys.argv[1]],text=True));assert pid>1;rows=dict(line.split(':',1) for line in pathlib.Path('/proc/'+str(pid)+'/status').read_text().splitlines() if ':' in line);print(json.dumps({key.lower():[int(v) for v in rows[key].split()] for key in ('Uid','Gid')}))"
        ids = json.loads(
            self.ct("python3", "-c", code, self.expected["blue_container"])
        )
        if ids != {"uid": [10001] * 4, "gid": [10001] * 4}:
            raise ValueError("Application process UID/GID differs in the CT namespace")
        return ids["uid"][1], ids["gid"][1]

    def record(self, event: str, receipt: dict | None = None) -> None:
        if self.journal is None:
            raise ValueError("Provisioning requires a durable private journal")
        self.journal.record(event, receipt)

    def create_lv(self, plan: dict) -> None:
        # Revalidate immediately before allocation; dry runs never get here.
        if storage_preflight(self.measure(), self.expected) != plan:
            raise ValueError("Storage plan changed")
        self.command(
            "lvcreate",
            "--type",
            "linear",
            "--zero",
            "n",
            "--wipesignatures",
            "n",
            "--size",
            "50G",
            "--name",
            "liberty-ct154-data",
            "--addtag",
            "liberty_office_data",
            "pve",
            mutation=True,
        )
        self.created = True

    def inspect_new_lv(self) -> dict:
        if not self.created:
            raise ValueError("No successful new-volume creation in this invocation")
        row = next(
            row
            for row in self._lvs()
            if row["vg_name"] == "pve" and row["lv_name"] == "liberty-ct154-data"
        )
        device = Path("/dev/pve/liberty-ct154-data").resolve(strict=True)
        info = device.stat()
        if (
            not stat.S_ISBLK(info.st_mode)
            or not re.fullmatch(r"/dev/dm-[0-9]+", str(device))
            or os.major(info.st_rdev) != int(row["lv_kernel_major"])
            or os.minor(info.st_rdev) != int(row["lv_kernel_minor"])
            or row["segtype"] != "linear"
            or int(self.command("blockdev", "--getsize64", str(device))) != 50 * GIB
        ):
            raise ValueError("Kernel and LVM device identities do not match")
        result = {
            "name": "pve/" + row["lv_name"],
            "uuid": row["lv_uuid"],
            "bytes": int(row["lv_size"]),
            "vg_uuid": self._vg()["vg_uuid"],
            "tags": sorted(filter(None, row["lv_tags"].split(","))),
            "signatures": json.loads(
                self.command("wipefs", "--no-act", "--json", str(device))
            )["signatures"],
            "device": str(device),
        }
        self.lv = result
        return result

    def format_new_lv(self, lv: dict) -> dict:
        # No forced formatter; compare the newly inspected device again.
        if self.inspect_new_lv() != lv:
            raise ValueError("New device changed before formatting")
        self.command(
            "mkfs.ext4", "-L", "liberty-data", "-m", "1", lv["device"], mutation=True
        )
        values = dict(
            line.split("=", 1)
            for line in self.command(
                "blkid",
                "-s",
                "UUID",
                "-s",
                "TYPE",
                "-s",
                "LABEL",
                "-o",
                "export",
                lv["device"],
            ).splitlines()
            if "=" in line
        )
        if values.get("LABEL") != "liberty-data":
            raise ValueError("The new filesystem label differs")
        return {"uuid": values["UUID"], "type": values["TYPE"], "lv_uuid": lv["uuid"]}

    def assert_attach_ready(self) -> None:
        config = self._config()
        if (
            config.get("mp1") is not None
            or config.get("lock") is not None
            or self._identity(config, self._lvs()) != self.expected
            or self._pending()
        ):
            raise ValueError(
                "CT identity, mount, lock or pending state changed before hotplug"
            )

    def mount_and_attach(self, filesystem: dict) -> dict:
        if self.lv is None:
            raise ValueError("The new device was not qualified")
        self.assert_attach_ready()
        device = Path("/dev/disk/by-uuid") / filesystem["uuid"]
        if device.resolve(strict=True) != Path(self.lv["device"]):
            raise ValueError("The filesystem UUID does not resolve to the new device")
        info = device.stat()
        major_minor = f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}"
        self.HOST_MOUNT.mkdir(mode=0o700)  # Existing path is never reused.
        unit_path = Path("/etc/systemd/system") / self.UNIT
        fd = os.open(
            unit_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644
        )
        with os.fdopen(fd, "w") as stream:
            stream.write(storage_mount_unit(filesystem["uuid"]))
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory(unit_path.parent)
        self.command("systemd-analyze", "verify", "--man=no", str(unit_path))
        self.command("systemctl", "daemon-reload", mutation=True)
        self.command("systemctl", "enable", "--now", self.UNIT, mutation=True)
        mounted = json.loads(
            self.command(
                "findmnt",
                "--json",
                "--mountpoint",
                str(self.HOST_MOUNT),
                "--output",
                "TARGET,UUID,MAJ:MIN,FSTYPE,OPTIONS",
            )
        )["filesystems"]
        if (
            len(mounted) != 1
            or mounted[0]["uuid"] != filesystem["uuid"]
            or mounted[0]["fstype"] != "ext4"
            or not {"nodev", "nosuid", "noexec"}
            <= set(mounted[0]["options"].split(","))
        ):
            raise ValueError(
                "The persistent host mount does not match the new filesystem"
            )
        os.chmod(self.HOST_MOUNT, 0o711)
        data = self.HOST_MOUNT / "data"
        data.mkdir(mode=0o700)
        os.chown(data, 110001, 110001)
        _sync_directory(self.HOST_MOUNT)
        self.assert_attach_ready()
        self.command(
            "pct",
            "set",
            "154",
            "-mp1",
            f"{self.HOST_MOUNT},mp={self.CT_MOUNT},backup=0",
            mutation=True,
        )
        config = self._config()
        if config.get("mp1") != f"{self.HOST_MOUNT},mp={self.CT_MOUNT},backup=0":
            raise ValueError(
                "The CT mount configuration differs from the intended binding"
            )
        ct_mount = json.loads(
            self.ct(
                "findmnt",
                "--json",
                "--mountpoint",
                self.CT_MOUNT,
                "--output",
                "TARGET,UUID,MAJ:MIN,FSTYPE,OPTIONS",
            )
        )["filesystems"]
        if len(ct_mount) != 1:
            raise ValueError("The live CT mount is not the new filesystem")
        verify_mount_identity(mounted[0], ct_mount[0], filesystem["uuid"], major_minor)
        probe = "import json,os,pathlib;d=pathlib.Path('/srv/liberty-data-next/data');p=d/'.uid-probe';fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.write(fd,b'probe');os.fsync(fd);os.close(fd);p.unlink();fd=os.open(d,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);os.fsync(fd);os.close(fd);s=os.statvfs(d);dev=d.stat().st_dev;print(json.dumps({'uid':os.geteuid(),'gid':os.getegid(),'device':str(os.major(dev))+':'+str(os.minor(dev)),'free_bytes':s.f_bavail*s.f_frsize}))"
        proof = json.loads(
            self.ct(
                "setpriv",
                "--reuid",
                "10001",
                "--regid",
                "10001",
                "--clear-groups",
                "python3",
                "-c",
                probe,
                mutation=True,
            )
        )
        if (
            proof.get("uid") != 10001
            or proof.get("gid") != 10001
            or proof.get("device") != major_minor
        ):
            raise ValueError("Live app-UID write proof was not on the new device")
        pid, ticks = self._process()
        return {
            "fs_uuid": filesystem["uuid"],
            "mp": "mp1",
            "ct_path": self.CT_MOUNT,
            "pending": self._pending(),
            "restart_required": False,
            "init_pid": pid,
            "init_start_ticks": ticks,
            "writable_uid": proof["uid"],
            "free_bytes": proof["free_bytes"],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--apply-provision", action="store_true")
    args = parser.parse_args(argv)
    config, digest = load_storage_config(args.config)
    if args.apply_provision:
        if args.journal is None:
            parser.error("--apply-provision requires a new private --journal")
        with StorageJournal(args.journal, digest) as journal:
            result = provision_storage(
                PveStorageOps(config["identity"], journal),
                config["identity"],
                apply=True,
            )
    else:
        result = provision_storage(
            PveStorageOps(config["identity"]), config["identity"]
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        StopIteration,
        subprocess.SubprocessError,
    ):
        print(
            "Storage admission failed; check the private configuration, measured identities and phase journal. No automatic retry or recovery was attempted.",
            file=sys.stderr,
        )
        raise SystemExit(1)
