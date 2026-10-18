"""Catch unsafe handoff ordering, uncertain restart and stale recovery."""

import importlib
import json
import threading
from pathlib import Path

import pytest


def controller():
    assert (Path(__file__).parents[1] / "scripts/handoff.py").is_file(), (
        "maintenance controller is absent"
    )
    return importlib.import_module("scripts.handoff")


class WriterFixture:
    """External boundaries only; the production controller owns all ordering."""

    def __init__(self, fail=None):
        self.events = []
        self.fail = fail
        self.maintenance = False
        self.retired = False
        self.writer = "blue"
        self.authority = "blue"
        self.values = ["before"]
        self.pending: threading.Event | None = None
        self.stopping = threading.Event()
        self.recovered = False

    def record(self, event):
        self.events.append(event)

    def preflight(self):
        if self.fail == "preflight":
            raise RuntimeError("private diagnostic must not reach journal")

    def enter_maintenance(self):
        self.maintenance = True

    def wait_old_proxy_workers(self):
        assert self.maintenance
        self.retired = True

    def graceful_stop_blue(self):
        assert self.maintenance and self.retired
        self.stopping.set()
        if self.pending is not None:
            self.pending.wait()
            self.values.append("disconnected-write")
        self.writer = None

    def reconcile(self):
        assert self.writer is None and self.retired
        self.authority = "candidate"

    def start_candidate(self):
        assert self.writer is None and self.maintenance
        if self.fail == "start":
            raise RuntimeError("candidate startup failed")
        self.writer = "candidate"

    def verify_candidate(self):
        assert self.writer == "candidate" and self.maintenance
        if self.fail == "verify":
            raise RuntimeError("candidate verification failed")

    def admit(self):
        self.maintenance = False
        self.retired = False
        self.values.append("accepted-by-candidate")

    def observe(self):
        if self.fail == "observe":
            raise RuntimeError("post-admission failure")

    def restore_authoritative(self):
        assert self.maintenance and self.retired
        # This boundary must recover the current authority, not the initial copy.
        assert self.authority == "candidate"
        self.writer = "recovered"
        self.recovered = True


def test_success_admits_only_after_real_stop_and_verification():
    handoff = controller()
    ops = WriterFixture()
    assert handoff.maintenance_handoff(ops) == {"phase": "observed", "accounts": "open"}
    assert ops.events == [
        "preflight.started",
        "preflight.complete",
        "maintenance.started",
        "maintenance.complete",
        "old-workers.started",
        "old-workers.complete",
        "old-process.started",
        "old-process.complete",
        "reconcile.started",
        "reconcile.complete",
        "candidate.started",
        "candidate.complete",
        "verified.started",
        "verified.complete",
        "admitted.started",
        "admitted.complete",
        "observed.started",
        "observed.complete",
    ]


def test_disconnected_write_blocks_reconcile_until_actual_writer_exit():
    handoff = controller()
    ops = WriterFixture()
    pending = threading.Event()
    ops.pending = pending
    thread = threading.Thread(target=handoff.maintenance_handoff, args=(ops,))
    thread.start()
    try:
        assert ops.stopping.wait(2)
        assert thread.is_alive()
        assert ops.writer == "blue" and ops.authority == "blue"
        assert "reconcile.started" not in ops.events
    finally:
        pending.set()
        thread.join(2)
    assert not thread.is_alive()
    assert ops.values == ["before", "disconnected-write", "accepted-by-candidate"]


@pytest.mark.parametrize("failure", ["start", "verify", "observe"])
def test_failures_hold_accounts_and_preserve_current_authority(failure):
    handoff = controller()
    ops = WriterFixture(failure)
    with pytest.raises(handoff.HandoffError, match="maintenance"):
        handoff.maintenance_handoff(ops)
    assert ops.maintenance and ops.retired and ops.recovered
    assert ops.writer == "recovered"
    assert ops.values == (
        ["before", "accepted-by-candidate"] if failure == "observe" else ["before"]
    )
    assert ops.events[-1] == "recovery.complete"


def test_preflight_failure_does_not_change_admission_or_writer():
    handoff = controller()
    ops = WriterFixture("preflight")
    with pytest.raises(handoff.HandoffError):
        handoff.maintenance_handoff(ops)
    assert not ops.maintenance and ops.writer == "blue"
    assert ops.events == ["preflight.started", "preflight.failed"]


def test_interruption_records_uncertainty_without_starting_another_writer():
    handoff = controller()
    ops = WriterFixture()

    def interrupted_stop():
        raise KeyboardInterrupt

    ops.graceful_stop_blue = interrupted_stop
    with pytest.raises(KeyboardInterrupt):
        handoff.maintenance_handoff(ops)
    assert ops.maintenance and ops.writer == "blue" and not ops.recovered
    assert ops.events[-1] == "old-process.interrupted"


def test_journal_is_exclusive_private_durable_and_rejects_replay(tmp_path):
    handoff = controller()
    path = tmp_path / "handoff.jsonl"
    with handoff.PhaseJournal(path, "a" * 64) as journal:
        journal.record("preflight.started")
        assert path.stat().st_mode & 0o777 == 0o600
        assert (
            json.loads(path.read_text().splitlines()[-1])["event"]
            == "preflight.started"
        )
        with pytest.raises((FileExistsError, RuntimeError)):
            handoff.PhaseJournal(path, "a" * 64)
        with pytest.raises(ValueError):
            journal.record("password=private")
    with pytest.raises(FileExistsError):
        handoff.PhaseJournal(path, "a" * 64)


def test_journal_rejects_symlink_without_touching_target(tmp_path):
    handoff = controller()
    target = tmp_path / "keep"
    target.write_text("unchanged")
    path = tmp_path / "journal"
    path.symlink_to(target)
    with pytest.raises(OSError):
        handoff.PhaseJournal(path, "a" * 64)
    assert target.read_text() == "unchanged"


def proxy_module():
    assert (Path(__file__).parents[1] / "scripts/liberty_proxy.py").is_file(), (
        "proxy controller is absent"
    )
    return importlib.import_module("scripts.liberty_proxy")


def test_worker_retirement_waits_for_process_identity_not_socket_counts(tmp_path):
    proxy = proxy_module()
    proc = tmp_path / "proc"
    process = proc / "42"
    process.mkdir(parents=True)
    # starttime is field22, after the comm field, even if its name contains ')'.
    (process / "stat").write_text("42 (nginx) worker) S 1 " + "0 " * 17 + "1234 0\n")
    old = proxy.ProcessIdentity(42, 1234)
    assert proxy.process_exists(old, proc)
    waits = []

    def retire(_):
        waits.append("waiting")
        assert proxy.process_exists(old, proc)
        (process / "stat").write_text("42 (new process) S 1 " + "0 " * 17 + "5678 0\n")

    proxy.wait_workers([old], proc=proc, pause=retire)
    assert waits == ["waiting"]
    assert not proxy.process_exists(old, proc)


def test_worker_capture_accepts_explicit_loader_without_including_unrelated_children(
    tmp_path,
):
    proxy = proxy_module()
    proc = tmp_path / "proc"
    for pid, parent, ticks, command in (
        (42, 1, 100, b"nginx: master process\0"),
        (
            43,
            42,
            101,
            b"/qual/ld.so\0--library-path\0/qual/lib\0nginx: worker process\0",
        ),
        (44, 42, 102, b"nginx: cache manager process\0"),
        (45, 1, 103, b"nginx: worker process\0"),
    ):
        path = proc / str(pid)
        path.mkdir(parents=True)
        (path / "stat").write_text(
            f"{pid} (nginx) S {parent} " + "0 " * 17 + f"{ticks} 0\n"
        )
        (path / "cmdline").write_bytes(command)
    assert proxy.capture_workers(proxy.ProcessIdentity(42, 100), proc) == [
        proxy.ProcessIdentity(43, 101)
    ]


def test_nginx_rendering_rejects_directive_injection():
    proxy = proxy_module()
    with pytest.raises(ValueError):
        proxy.maintenance_config(
            portal="office.test; include /private/*",
            private="edit.test",
            demo="demo.test",
            public_upstream="127.0.0.1:18697",
        )


def deploy_module():
    assert (Path(__file__).parents[1] / "scripts/deploy_liberty.py").is_file(), (
        "deployment CLI is absent"
    )
    return importlib.import_module("scripts.deploy_liberty")


def test_cli_defaults_to_nonmutating_private_config_validation(tmp_path, capsys):
    deploy = deploy_module()
    script = tmp_path / "must-not-run.py"
    script.write_text('raise RuntimeError("must not execute during dry run")\n')
    config = {
        "schema": 1,
        "run_id": "synthetic-001",
        "identity": {
            "ct": 154,
            "blue_container": "d" * 64,
            "blue_image": "sha256:" + "b" * 64,
        },
        "commands": {
            name: {"argv": ["/usr/local/bin/python", str(script)], "timeout": 30}
            for name in deploy.COMMANDS
        },
    }
    for name in deploy.WAIT_COMMANDS:
        config["commands"][name]["timeout"] = None
    path = tmp_path / "private.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    journal = tmp_path / "phases.jsonl"
    assert deploy.main(["--config", str(path), "--journal", str(journal)]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["apply"] is False
    assert not journal.exists()
    assert "must-not-run" not in output
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        deploy.main(["--config", str(path), "--journal", str(journal)])


def test_command_config_disallows_forced_stop_deadlines_and_shell_strings(tmp_path):
    deploy = deploy_module()
    base = {
        "schema": 1,
        "run_id": "synthetic-001",
        "identity": {
            "ct": 154,
            "blue_container": "d" * 64,
            "blue_image": "sha256:" + "b" * 64,
        },
        "commands": {
            name: {
                "argv": ["/usr/bin/true"],
                "timeout": None if name in deploy.WAIT_COMMANDS else 30,
            }
            for name in deploy.COMMANDS
        },
    }
    path = tmp_path / "private.json"
    path.write_text(json.dumps(base))
    path.chmod(0o600)
    base["commands"]["graceful_stop_blue"]["timeout"] = 10
    path.write_text(json.dumps(base))
    with pytest.raises(ValueError, match="unlimited"):
        deploy.load_config(path)
    base["commands"]["graceful_stop_blue"]["timeout"] = None
    base["commands"]["preflight"]["argv"] = "sh -c unsafe"
    path.write_text(json.dumps(base))
    with pytest.raises(ValueError, match="argv"):
        deploy.load_config(path)
