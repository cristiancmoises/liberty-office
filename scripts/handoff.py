"""Account-only maintenance policy; commands and storage live at the boundary."""

from __future__ import annotations

import fcntl
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Self


class MaintenanceOps(Protocol):
    def preflight(self) -> object: ...
    def enter_maintenance(self) -> object: ...
    def wait_old_proxy_workers(self) -> object: ...
    def graceful_stop_blue(self) -> object: ...
    def reconcile(self) -> object: ...
    def start_candidate(self) -> object: ...
    def verify_candidate(self) -> object: ...
    def admit(self) -> object: ...
    def observe(self) -> object: ...
    def restore_authoritative(self) -> object: ...
    def record(self, event: str) -> None: ...


class HandoffError(RuntimeError):
    """The journal identifies the failed phase without exposing command output."""


def maintenance_handoff(ops: MaintenanceOps) -> dict[str, str]:
    """Never start a second owner before both proxy and process retirement.

    Boundary operations return only after their real completion. In particular,
    a stop timeout, disconnected command or empty socket list is not an exit.
    Interruptions are intentionally not retried: a daemon stop may still run.
    """
    steps = (
        ("preflight", ops.preflight),
        ("maintenance", ops.enter_maintenance),
        ("old-workers", ops.wait_old_proxy_workers),
        ("old-process", ops.graceful_stop_blue),
        ("reconcile", ops.reconcile),
        ("candidate", ops.start_candidate),
        ("verified", ops.verify_candidate),
        ("admitted", ops.admit),
        ("observed", ops.observe),
    )
    phase = "preflight"
    try:
        for phase, operation in steps:
            ops.record(f"{phase}.started")
            operation()
            ops.record(f"{phase}.complete")
    except (KeyboardInterrupt, SystemExit):
        ops.record(f"{phase}.interrupted")
        raise
    except Exception as failure:
        ops.record(f"{phase}.failed")
        if phase != "preflight":
            # Admission may have partly succeeded. Re-establish the boundary
            # before recovery, including retirement of that proxy generation.
            ops.record("recovery.started")
            try:
                ops.enter_maintenance()
                ops.wait_old_proxy_workers()
                ops.restore_authoritative()
            except (KeyboardInterrupt, SystemExit):
                ops.record("recovery.interrupted")
                raise
            except Exception as recovery_failure:
                ops.record("recovery.failed")
                raise HandoffError(
                    f"{phase} failed; account maintenance requires operator recovery"
                ) from recovery_failure
            ops.record("recovery.complete")
        message = (
            "no admission change attempted"
            if phase == "preflight"
            else "account maintenance was not lifted"
        )
        raise HandoffError(f"{phase} failed; {message}") from failure
    return {"phase": "observed", "accounts": "open"}


_PHASES = frozenset(
    (
        "preflight",
        "maintenance",
        "old-workers",
        "old-process",
        "reconcile",
        "candidate",
        "verified",
        "admitted",
        "observed",
        "recovery",
    )
)
_STATES = frozenset(("started", "complete", "failed", "interrupted"))


class PhaseJournal:
    """Create-once, fsynced, private journal; an uncertain run is never replayed."""

    def __init__(self, path: Path, config_sha256: str):
        if not re.fullmatch(r"[a-f0-9]{64}", config_sha256):
            raise ValueError("Expected the exact configuration SHA-256")
        self.path = Path(path)
        fd = os.open(
            self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        self._file = os.fdopen(fd, "w", encoding="utf-8")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._append({"schema": 1, "config_sha256": config_sha256})
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except BaseException:
            self._file.close()
            raise

    def _append(self, value: dict[str, object]) -> None:
        self._file.write(json.dumps(value, sort_keys=True) + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())

    def record(self, event: str) -> None:
        phase, separator, state = event.partition(".")
        if not separator or phase not in _PHASES or state not in _STATES:
            raise ValueError("Unknown handoff event")
        self._append({"event": event, "at": datetime.now(timezone.utc).isoformat()})

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self._file.close()
