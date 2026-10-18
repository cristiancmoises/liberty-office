"""Reject unsafe provisioning and stale/offline reconciliation before any write."""

import copy
import importlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ORIGIN, bootstrap, csrf
from fastapi.testclient import TestClient

from liberty.app import create_app
from liberty.config import Settings

GIB = 1073741824
IDENTITY = {
    "pve": "securityops",
    "ct": 154,
    "ct_hostname": "office-suite.lab",
    "init_pid": 42,
    "init_start_ticks": 99,
    "blue_container": "d" * 64,
    "blue_image": "sha256:" + "b" * 64,
    "vg_uuid": "DncLc3-V1As-9RAg-8ITm-WONq-Rrs3-i38xUy",
    "root_lv_uuid": "7nDkWh-Lk3N-fHab-Gy03-T2sT-WOKY-nNGaF1",
}


def storage_module():
    assert (Path(__file__).parents[1] / "scripts/liberty_storage.py").is_file(), (
        "guarded storage adapter is absent"
    )
    return importlib.import_module("scripts.liberty_storage")


def facts():
    return {
        "identity": copy.deepcopy(IDENTITY),
        "ram_available": 4 * GIB,
        "pve_root_free": 8 * GIB,
        "ct_root_free": 5 * GIB,
        "vg_free": 60 * GIB,
        "backup_free": GIB + 2000,
        "source_bytes": 1000,
        "thin_data_percent": 79.9,
        "thin_metadata_percent": 79.9,
        "existing_data_lv": False,
        "device_signatures": [],
        "mp1": None,
        "pending": [],
        "active_tasks": [],
        "ct_lock": None,
        "uid_map": [0, 100000, 65536],
        "gid_map": [0, 100000, 65536],
        "app_uid": 10001,
        "app_gid": 10001,
        "hotplug_supported": True,
    }


def test_exact_storage_boundaries_produce_only_the_intended_new_volume():
    storage = storage_module()
    assert storage.storage_preflight(facts(), IDENTITY) == {
        "lv": "pve/liberty-ct154-data",
        "bytes": 53687091200,
        "mp": "mp1",
        "ct_path": "/srv/liberty-data-next",
        "global_quota": 48318382080,
        "min_free_bytes": 1073741824,
        "host_uid": 110001,
        "host_gid": 110001,
    }


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ram_available", 4 * GIB - 1),
        ("pve_root_free", 8 * GIB - 1),
        ("ct_root_free", 5 * GIB - 1),
        ("vg_free", 60 * GIB - 1),
        ("backup_free", GIB + 1999),
        ("thin_data_percent", 80),
        ("thin_metadata_percent", 80),
        ("thin_data_percent", float("nan")),
        ("existing_data_lv", True),
        ("device_signatures", ["ext4"]),
        ("mp1", {"mp": "/already-used"}),
        ("pending", ["mp1"]),
        ("active_tasks", ["running"]),
        ("ct_lock", "snapshot-delete"),
        ("uid_map", [0, 200000, 65536]),
        ("gid_map", [0, 200000, 65536]),
        ("app_uid", 0),
        ("app_gid", 0),
        ("hotplug_supported", False),
        ("ct_root_free", "large"),
        ("source_bytes", -1),
    ],
)
def test_unsafe_storage_facts_abort_before_planning(key, value):
    storage = storage_module()
    actual = facts()
    actual[key] = value
    with pytest.raises(ValueError):
        storage.storage_preflight(actual, IDENTITY)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ct", 155),
        ("ct_hostname", "another.lab"),
        ("blue_container", "a" * 64),
        ("blue_image", "sha256:" + "c" * 64),
        ("init_pid", 43),
        ("init_start_ticks", 100),
        ("vg_uuid", "different"),
        ("root_lv_uuid", "different"),
        ("pve", "different"),
    ],
)
def test_changed_host_container_image_or_device_identity_aborts(key, value):
    storage = storage_module()
    actual = facts()
    actual["identity"][key] = value
    with pytest.raises(ValueError):
        storage.storage_preflight(actual, IDENTITY)


def prepare_data(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "source", apps_dir=tmp_path / "apps", origin=ORIGIN
    )
    with TestClient(
        create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as client:
        bootstrap(client, settings)
        first = client.post(
            "/api/files",
            params={"name": "history.txt"},
            content=b"old",
            headers=csrf(client),
        ).json()
        current = client.put(
            "/api/files/" + first["id"] + "/content",
            content=b"new",
            headers={**csrf(client), "If-Match": first["etag"]},
        ).json()
        client.delete("/api/files/" + first["id"], headers=csrf(client))
        cookie = client.cookies.get("liberty_session")
        assert cookie is not None
        with settings.data_dir.joinpath("mfa.key").open("rb") as stream:
            key = stream.read()
        with app_database(settings.data_dir) as db:
            sessions = db.execute("SELECT * FROM sessions ORDER BY id").fetchall()
            users = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    return settings, first, current, cookie, key, sessions, users


def app_database(data):
    return sqlite3.connect(data / "liberty.db")


def test_authoritative_snapshot_preserves_sessions_mfa_history_trash_and_quotas(
    tmp_path,
):
    storage = storage_module()
    settings, first, current, cookie, key, sessions, users = prepare_data(tmp_path)
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    backup = tmp_path / "current-backup.tar.gz"
    receipt = storage.offline_snapshot(settings.data_dir, target, backup)
    assert receipt["verified"] is True
    assert backup.stat().st_mode & 0o777 == 0o600
    assert (target / "mfa.key").read_bytes() == key
    with app_database(target) as db:
        assert db.execute("SELECT * FROM sessions ORDER BY id").fetchall() == sessions
        assert db.execute("SELECT * FROM users ORDER BY id").fetchall() == users
        assert db.execute("SELECT COUNT(*) FROM versions").fetchone()[0] == 2
    destination = Settings(data_dir=target, apps_dir=settings.apps_dir, origin=ORIGIN)
    with TestClient(
        create_app(destination), base_url=ORIGIN, headers={"Origin": ORIGIN}
    ) as client:
        client.cookies.set("liberty_session", cookie)
        assert client.get("/api/auth/status").json()["state"] == "full"
        assert (
            client.get("/api/files", params={"view": "trash"}).json()["files"][0]["id"]
            == first["id"]
        )
        assert (
            client.post(
                "/api/files/" + first["id"] + "/restore", headers=csrf(client)
            ).status_code
            == 200
        )
        assert client.get("/api/files/" + first["id"] + "/content").content == b"new"
        assert (
            client.get(
                "/api/files/" + first["id"] + "/content",
                params={"version": first["version"]},
            ).content
            == b"old"
        )
        assert current["version"] != first["version"]


def test_snapshot_refuses_an_active_writer_and_nonempty_destination(env, tmp_path):
    storage = storage_module()
    _, client, settings = env
    bootstrap(client, settings)
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(RuntimeError):
        storage.offline_snapshot(settings.data_dir, target, tmp_path / "backup.tar.gz")
    assert not (target / "liberty.db").exists()
    (target / "keep").write_text("keep this")
    with pytest.raises(ValueError):
        storage.offline_snapshot(settings.data_dir, target, tmp_path / "another.tar.gz")
    assert (target / "keep").read_text() == "keep this"


def test_snapshot_detects_a_write_in_the_backup_reacquisition_gap(
    tmp_path, monkeypatch
):
    storage = storage_module()
    settings, *_ = prepare_data(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    cli = importlib.import_module("liberty.cli")
    actual = cli.make_backup

    def intervening_write(data, stream):
        result = actual(data, stream)
        with app_database(data) as db:
            db.execute("UPDATE users SET name='accepted after snapshot'")
        return result

    monkeypatch.setattr(cli, "make_backup", intervening_write)
    with pytest.raises(ValueError, match="changed"):
        storage.offline_snapshot(settings.data_dir, target, tmp_path / "backup.tar.gz")
    assert not (target / "liberty.db").exists()
    with app_database(settings.data_dir) as db:
        assert (
            db.execute("SELECT name FROM users").fetchone()[0]
            == "accepted after snapshot"
        )


def test_snapshot_rejects_symlink_before_reading_outside_private_volume(tmp_path):
    storage = storage_module()
    settings, *_ = prepare_data(tmp_path)
    outside = tmp_path / "outside-key"
    original = settings.data_dir / "mfa.key"
    original.rename(outside)
    original.symlink_to(outside)
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(ValueError):
        storage.offline_snapshot(settings.data_dir, target, tmp_path / "backup.tar.gz")
    assert not (target / "liberty.db").exists()
    assert outside.exists()


def test_old_writer_protection_is_offline_and_keeps_public_markers(tmp_path):
    storage = storage_module()
    settings, *_ = prepare_data(tmp_path)
    with app_database(settings.data_dir) as db:
        user = db.execute("SELECT id FROM users").fetchone()[0]
        db.execute(
            "INSERT INTO public_accounts(user_id,created_at) VALUES(?,1)", (user,)
        )
    assert storage.protect_public_accounts(settings.data_dir) == 1
    with app_database(settings.data_dir) as db:
        assert db.execute(
            "SELECT established_at,cleanup_protected FROM public_accounts"
        ).fetchone() == (None, 1)
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    with (
        TestClient(create_app(settings), base_url=ORIGIN, headers={"Origin": ORIGIN}),
        pytest.raises(RuntimeError),
    ):
        storage.protect_public_accounts(settings.data_dir)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("blue_container", "liberty-office-office-1"),
        ("blue_image", "liberty-office:latest"),
        ("init_pid", 0),
        ("init_start_ticks", True),
        ("vg_uuid", "not-a-uuid"),
    ],
)
def test_storage_identity_must_be_exact_even_when_config_and_live_values_match(
    key, value
):
    storage = storage_module()
    expected = copy.deepcopy(IDENTITY)
    expected[key] = value
    actual = facts()
    actual["identity"] = expected
    with pytest.raises(ValueError):
        storage.storage_preflight(actual, expected)


class ProvisionFixture:
    def __init__(self):
        self.operations = []
        self.events = []
        self.lv = {
            "name": "pve/liberty-ct154-data",
            "bytes": 53687091200,
            "uuid": "ABC123-1234-5678-9012-abcd-efgh-ABC123",
            "vg_uuid": IDENTITY["vg_uuid"],
            "tags": ["liberty_office_data"],
            "signatures": [],
        }
        self.mount = {
            "fs_uuid": "c00bad00-1234-4567-8901-123456789abc",
            "init_pid": 42,
            "init_start_ticks": 99,
            "pending": [],
            "mp": "mp1",
            "ct_path": "/srv/liberty-data-next",
            "writable_uid": 10001,
            "free_bytes": 48 * GIB,
            "restart_required": False,
        }

    def measure(self):
        self.operations.append("measure")
        return facts()

    def record(self, event, receipt=None):
        self.events.append(event)

    def create_lv(self, plan):
        self.operations.append("create")
        assert plan["lv"] == "pve/liberty-ct154-data"

    def inspect_new_lv(self):
        self.operations.append("inspect")
        return self.lv

    def format_new_lv(self, lv):
        self.operations.append("format")
        assert lv["uuid"] == self.lv["uuid"]
        return {
            "uuid": "c00bad00-1234-4567-8901-123456789abc",
            "type": "ext4",
            "lv_uuid": lv["uuid"],
        }

    def mount_and_attach(self, filesystem):
        self.operations.append("attach")
        assert filesystem["uuid"] == "c00bad00-1234-4567-8901-123456789abc"
        return self.mount


def test_provisioning_is_dry_run_by_default():
    storage = storage_module()
    ops = ProvisionFixture()
    result = storage.provision_storage(ops, IDENTITY)
    assert result["applied"] is False
    assert ops.operations == ["measure"] and ops.events == []


def test_provisioning_module_imports_without_application_dependencies():
    path = Path(__file__).parents[1] / "scripts/liberty_storage.py"
    code = (
        "import importlib.util,sys;"
        's=importlib.util.spec_from_file_location("storage",sys.argv[1]);'
        "m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", code, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("name", "pve/vm-154-disk-0"),
        ("uuid", IDENTITY["root_lv_uuid"]),
        ("bytes", 21474836480),
        ("tags", []),
        ("signatures", ["ext4"]),
    ],
)
def test_existing_wrong_or_signed_device_is_never_formatted(key, value):
    storage = storage_module()
    ops = ProvisionFixture()
    ops.lv[key] = value
    with pytest.raises(ValueError):
        storage.provision_storage(ops, IDENTITY, apply=True)
    assert "format" not in ops.operations and "attach" not in ops.operations


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("init_pid", 43),
        ("init_start_ticks", 100),
        ("pending", ["mp1"]),
        ("restart_required", True),
        ("writable_uid", 0),
        ("free_bytes", 46 * GIB - 1),
        ("fs_uuid", "11111111-1111-1111-1111-111111111111"),
    ],
)
def test_unqualified_hotplug_is_not_promoted_or_restarted(key, value):
    storage = storage_module()
    ops = ProvisionFixture()
    ops.mount[key] = value
    with pytest.raises(ValueError):
        storage.provision_storage(ops, IDENTITY, apply=True)
    assert "provision.complete" not in ops.events


def test_verified_empty_volume_is_the_only_successful_provision_result():
    storage = storage_module()
    ops = ProvisionFixture()
    result = storage.provision_storage(ops, IDENTITY, apply=True)
    assert result["applied"] is True and result["mount_verified"] is True
    assert ops.operations == ["measure", "create", "inspect", "format", "attach"]
    assert ops.events == [
        "lv-create.started",
        "lv-create.complete",
        "filesystem.started",
        "filesystem.complete",
        "attach.started",
        "attach.complete",
        "provision.complete",
    ]


def test_attach_journal_preserves_live_uid_capacity_and_restart_evidence():
    storage = storage_module()
    ops = ProvisionFixture()
    receipts = {}
    ops.record = lambda event, receipt=None: receipts.update({event: receipt})
    storage.provision_storage(ops, IDENTITY, apply=True)
    assert receipts["attach.complete"]["writable_uid"] == 10001
    assert receipts["attach.complete"]["free_bytes"] >= 46 * GIB
    assert receipts["attach.complete"]["restart_required"] is False


def test_storage_journal_is_private_create_once_and_rejects_secret_fields(tmp_path):
    storage = storage_module()
    path = tmp_path / "provision.jsonl"
    with storage.StorageJournal(path, "a" * 64) as journal:
        journal.record(
            "filesystem.complete",
            {"uuid": "c00bad00-1234-4567-8901-123456789abc", "type": "ext4"},
        )
        assert path.stat().st_mode & 0o777 == 0o600
        before = path.read_text()
        with pytest.raises(ValueError):
            journal.record("filesystem.complete", {"password": "must-not-be-written"})
        assert path.read_text() == before and "must-not-be-written" not in before
    with pytest.raises(FileExistsError):
        storage.StorageJournal(path, "a" * 64)


def test_storage_cli_rejects_nonprivate_config_before_any_host_operation(tmp_path):
    path = tmp_path / "private.json"
    path.write_text("{}")
    path.chmod(0o644)
    script = Path(__file__).parents[1] / "scripts/liberty_storage.py"
    result = subprocess.run(
        [sys.executable, "-I", "-S", str(script), "--config", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, "Storage CLI did not validate its configuration"
    assert "private configuration" in result.stderr


@pytest.mark.parametrize("relative", ["liberty.db", ".", "blobs"])
def test_failed_destination_durability_never_returns_a_verified_snapshot(
    tmp_path, monkeypatch, relative
):
    storage = storage_module()
    settings, *_ = prepare_data(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    actual = os.fsync
    failing = target / relative

    def cannot_sync(fd):
        if Path(os.readlink("/proc/self/fd/" + str(fd))) == failing:
            raise OSError("Synthetic destination durability failure")
        return actual(fd)

    monkeypatch.setattr(os, "fsync", cannot_sync)
    with pytest.raises(OSError, match="durability"):
        storage.offline_snapshot(settings.data_dir, target, tmp_path / "backup.tar.gz")
    assert (settings.data_dir / "liberty.db").is_file()


def test_invalid_blob_reference_is_rejected_before_reading_outside_the_volume(
    tmp_path, monkeypatch
):
    storage = storage_module()
    settings, *_ = prepare_data(tmp_path)
    outside = tmp_path / "outside-key"
    outside.write_bytes(b"synthetic-outside-content")
    with app_database(settings.data_dir) as db:
        db.execute("UPDATE versions SET id='../../outside-key' WHERE sequence=1")
    target = tmp_path / "target"
    target.mkdir()
    cli = importlib.import_module("liberty.cli")
    actual = cli.file_hash
    outside_reads = []

    def observe_read(path):
        if Path(path).resolve() == outside:
            outside_reads.append(True)
        return actual(path)

    monkeypatch.setattr(cli, "file_hash", observe_read)
    with pytest.raises(ValueError):
        storage.offline_snapshot(settings.data_dir, target, tmp_path / "backup.tar.gz")
    assert outside_reads == []


def private_config(tmp_path, identity=None):
    path = tmp_path / "storage.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "run_id": "storage-test-01",
                "identity": IDENTITY if identity is None else identity,
            }
        )
    )
    path.chmod(0o600)
    return path


def test_private_storage_config_rejects_weak_identity_before_host_commands(tmp_path):
    storage = storage_module()
    with pytest.raises(ValueError, match="identit"):
        storage.load_storage_config(private_config(tmp_path, {"ct": 154}))


def test_storage_cli_is_dry_run_without_creating_a_journal(
    tmp_path, monkeypatch, capsys
):
    storage = storage_module()
    fixture = ProvisionFixture()
    monkeypatch.setattr(storage, "PveStorageOps", lambda *_: fixture)
    assert storage.main(["--config", str(private_config(tmp_path))]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["applied"] is False
    assert fixture.operations == ["measure"] and fixture.events == []


def test_mount_unit_is_uuid_bound_fail_closed_and_bounds_device_wait():
    storage = storage_module()
    value = storage.storage_mount_unit("c00bad00-1234-4567-8901-123456789abc")
    assert "What=/dev/disk/by-uuid/c00bad00-1234-4567-8901-123456789abc\n" in value
    assert "Where=/srv/liberty-data-ct154\n" in value
    assert "JobTimeoutSec=45s\n" in value and "TimeoutSec=30s\n" in value
    assert "DirectoryMode=0700\n" in value
    assert "Options=nodev,nosuid,noexec,noatime\n" in value
    assert "WantedBy=multi-user.target\n" in value
    assert (
        "Requires=pve-guests" not in value and "x-systemd.device-timeout" not in value
    )
    with pytest.raises(ValueError):
        storage.storage_mount_unit("../../another-device")


def test_pve_identity_uses_verified_fqdn_not_the_short_config_hostname(monkeypatch):
    storage = storage_module()
    ops = storage.PveStorageOps(IDENTITY)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(ops, "command", lambda *args: "securityops")
    monkeypatch.setattr(ops, "_process", lambda: (42, 99))
    monkeypatch.setattr(ops, "_vg", lambda: {"vg_uuid": IDENTITY["vg_uuid"]})
    calls = []

    def ct(*args):
        calls.append(args)
        if args == ("hostname", "-f"):
            return "office-suite.lab"
        assert args[:2] == ("docker", "inspect")
        return json.dumps(
            {
                "id": IDENTITY["blue_container"],
                "image": IDENTITY["blue_image"],
                "running": True,
                "restarts": 0,
            }
        )

    monkeypatch.setattr(ops, "ct", ct)
    row = {
        "vg_name": "pve",
        "lv_name": "vm-154-disk-0",
        "lv_uuid": IDENTITY["root_lv_uuid"],
    }
    config = {"rootfs": "local-lvm:vm-154-disk-0,size=30G", "hostname": "office-suite"}
    assert ops._identity(config, [row]) == IDENTITY
    assert ("hostname", "-f") in calls
    with pytest.raises(ValueError):
        ops._identity({**config, "hostname": "other-suite"}, [row])


def test_existing_host_mount_path_aborts_before_any_allocation(tmp_path, monkeypatch):
    storage = storage_module()
    ops = storage.PveStorageOps(IDENTITY)
    monkeypatch.setattr(ops, "HOST_MOUNT", tmp_path)
    monkeypatch.setattr(
        ops, "_config", lambda: pytest.fail("Existing path was not rejected")
    )
    with pytest.raises(ValueError, match="mount"):
        ops.measure()


def test_formatter_requires_successful_creation_in_the_same_invocation(monkeypatch):
    storage = storage_module()
    ops = storage.PveStorageOps(IDENTITY)
    monkeypatch.setattr(
        ops, "command", lambda *_: pytest.fail("No formatter is allowed")
    )
    with pytest.raises(ValueError, match="creation"):
        ops.format_new_lv({})


@pytest.mark.parametrize("change", [{"mp1": "/occupied"}, {"lock": "snapshot"}])
def test_mount_conflict_after_preflight_is_rejected_before_hotplug(monkeypatch, change):
    storage = storage_module()
    ops = storage.PveStorageOps(IDENTITY)
    monkeypatch.setattr(ops, "_config", lambda: change)
    monkeypatch.setattr(ops, "_lvs", list)
    monkeypatch.setattr(ops, "_identity", lambda *_: IDENTITY)
    monkeypatch.setattr(ops, "_pending", list)
    with pytest.raises(ValueError, match="mount|lock"):
        ops.assert_attach_ready()


def test_new_lv_creation_does_not_clear_signatures_before_inspection(monkeypatch):
    storage = storage_module()
    ops = storage.PveStorageOps(IDENTITY)
    monkeypatch.setattr(ops, "measure", facts)
    commands = []
    monkeypatch.setattr(ops, "command", lambda *args, **kwargs: commands.append(args))
    ops.create_lv(storage.storage_preflight(facts(), IDENTITY))
    command = commands[0]
    assert command[command.index("--zero") + 1] == "n"
    assert command[command.index("--wipesignatures") + 1] == "n"


def mount_facts():
    host = {
        "uuid": "c00bad00-1234-4567-8901-123456789abc",
        "maj:min": "252:57",
        "target": "/srv/liberty-data-ct154",
        "fstype": "ext4",
        "options": "rw,nosuid,nodev,noexec,noatime",
    }
    ct = {**host, "uuid": None, "target": "/srv/liberty-data-next"}
    return host, ct


def test_unprivileged_ct_mount_is_proven_by_host_uuid_and_shared_kernel_device():
    storage = storage_module()
    host, ct = mount_facts()
    storage.verify_mount_identity(host, ct, host["uuid"], "252:57")


@pytest.mark.parametrize(
    "field,value",
    [
        ("maj:min", "252:1"),
        ("target", "/wrong"),
        ("fstype", "tmpfs"),
        ("uuid", "11111111-1111-1111-1111-111111111111"),
        ("options", "rw"),
    ],
)
def test_matching_path_without_matching_live_device_is_not_accepted(field, value):
    storage = storage_module()
    host, ct = mount_facts()
    with pytest.raises(ValueError):
        storage.verify_mount_identity(
            host, {**ct, field: value}, host["uuid"], "252:57"
        )


@pytest.mark.parametrize(
    "uid,gid,valid",
    [
        ([10001] * 4, [10001] * 4, True),
        ([110001] * 4, [10001] * 4, False),
        ([10001] * 4, [110001] * 4, False),
        ([10001, 10001, 10001, 0], [10001] * 4, False),
    ],
)
def test_application_identity_is_measured_in_the_ct_process_namespace(
    monkeypatch, uid, gid, valid
):
    storage = storage_module()
    ops = storage.PveStorageOps(IDENTITY)
    monkeypatch.setattr(ops, "ct", lambda *_: json.dumps({"uid": uid, "gid": gid}))
    if valid:
        assert ops.application_ids() == (10001, 10001)
    else:
        with pytest.raises(ValueError):
            ops.application_ids()
