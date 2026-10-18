"""Run a private, identity-pinned maintenance handoff. Dry-run is the default.

The private command adapters are operator-owned files, never an HTTP interface.
They must validate real state, return a small JSON receipt and never retry a
mutation. Storage-specific adapters are qualified separately before production.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

try:
    from .handoff import HandoffError, PhaseJournal, maintenance_handoff
except ImportError:
    from handoff import HandoffError, PhaseJournal, maintenance_handoff


COMMANDS = (
    "preflight",
    "enter_maintenance",
    "wait_old_proxy_workers",
    "graceful_stop_blue",
    "reconcile",
    "start_candidate",
    "verify_candidate",
    "admit",
    "observe",
    "restore_authoritative",
)
WAIT_COMMANDS = frozenset(
    ("wait_old_proxy_workers", "graceful_stop_blue", "restore_authoritative")
)


def load_config(path: Path) -> tuple[dict, str]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
        ):
            raise ValueError(
                "Configuration must be a private, operator-owned regular file"
            )
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("Configuration exceeds 64 KiB")
    config = json.loads(raw)
    if (
        not isinstance(config, dict)
        or set(config) != {"schema", "run_id", "identity", "commands"}
        or config["schema"] != 1
        or not re.fullmatch(r"[a-z0-9][a-z0-9-]{7,63}", config["run_id"])
    ):
        raise ValueError("Invalid handoff configuration")
    identity = config["identity"]
    if (
        not isinstance(identity, dict)
        or set(identity) != {"ct", "blue_container", "blue_image"}
        or identity["ct"] != 154
        or not re.fullmatch(r"[a-f0-9]{64}", identity["blue_container"])
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", identity["blue_image"])
    ):
        raise ValueError("Expected exact Liberty CT/container/image identities")
    if not isinstance(config["commands"], dict) or set(config["commands"]) != set(
        COMMANDS
    ):
        raise ValueError("Every maintenance boundary is required")
    for name, command in config["commands"].items():
        if not isinstance(command, dict) or set(command) != {"argv", "timeout"}:
            raise ValueError("Expected argv and timeout for each command")
        argv = command["argv"]
        if (
            not isinstance(argv, list)
            or not 1 <= len(argv) <= 64
            or not all(
                isinstance(arg, str) and 0 < len(arg) <= 4096 and "\0" not in arg
                for arg in argv
            )
            or not Path(argv[0]).is_absolute()
        ):
            raise ValueError(
                "Commands require explicit absolute executable argv, not shell strings"
            )
        timeout = command["timeout"]
        if name in WAIT_COMMANDS:
            if timeout is not None:
                raise ValueError(
                    "Worker/owner waits and recovery require unlimited waiting"
                )
        elif type(timeout) is not int or not 1 <= timeout <= 3600:
            raise ValueError("Other command boundaries require a bounded timeout")
    return config, hashlib.sha256(raw).hexdigest()


class CommandOps:
    def __init__(self, config: dict, journal: PhaseJournal):
        self.config = config
        self.journal = journal

    def record(self, event: str) -> None:
        self.journal.record(event)
        print(json.dumps({"event": event}), flush=True)

    def _run(self, name: str) -> dict:
        command = self.config["commands"][name]
        # No shell, request replay, inherited stdin or raw command diagnostics.
        result = subprocess.run(
            command["argv"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=command["timeout"],
            check=False,
        )
        if result.returncode or len(result.stdout) > 4096:
            raise HandoffError(f"{name} did not return a successful bounded receipt")
        value = json.loads(result.stdout)
        if not isinstance(value, dict) or value.get("ok") is not True:
            raise HandoffError(f"{name} did not attest successful completion")
        return value

    def preflight(self) -> None:
        if self._run("preflight").get("identity") != self.config["identity"]:
            raise HandoffError("Live identity differs from the pinned configuration")

    def enter_maintenance(self) -> None:
        if self._run("enter_maintenance").get("maintenance") is not True:
            raise HandoffError("Private admission is not proven closed")

    def wait_old_proxy_workers(self) -> None:
        if self._run("wait_old_proxy_workers").get("old_workers_exited") is not True:
            raise HandoffError("Old worker retirement is not proven")

    def graceful_stop_blue(self) -> None:
        value = self._run("graceful_stop_blue")
        if (
            value.get("old_process_exited") is not True
            or value.get("lock_released") is not True
        ):
            raise HandoffError("Old process exit and released volume lock are required")

    def reconcile(self) -> None:
        if self._run("reconcile").get("reconciled") is not True:
            raise HandoffError("Authoritative reconciliation is not proven")

    def start_candidate(self) -> None:
        if self._run("start_candidate").get("single_writer") is not True:
            raise HandoffError("Exactly one candidate owner is required")

    def verify_candidate(self) -> None:
        if self._run("verify_candidate").get("verified") is not True:
            raise HandoffError("Candidate acceptance is not proven")

    def admit(self) -> None:
        if self._run("admit").get("accounts_open") is not True:
            raise HandoffError("Account admission is not proven")

    def observe(self) -> None:
        if self._run("observe").get("observed") is not True:
            raise HandoffError("Post-admission observation is incomplete")

    def restore_authoritative(self) -> None:
        value = self._run("restore_authoritative")
        if (
            value.get("maintenance") is not True
            or value.get("authoritative") is not True
        ):
            raise HandoffError("Authoritative recovery under maintenance is not proven")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    config, digest = load_config(args.config)
    if not args.apply:
        print(
            json.dumps(
                {
                    "apply": False,
                    "run_id": config["run_id"],
                    "identity": config["identity"],
                    "phases": list(COMMANDS),
                    "config_sha256": digest,
                }
            )
        )
        return 0
    if args.journal.parent.stat().st_mode & 0o077:
        raise ValueError("Journal directory must be private")
    with PhaseJournal(args.journal, digest) as journal:
        result = maintenance_handoff(CommandOps(config, journal))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, HandoffError):
        raise SystemExit(
            "Handoff stopped; inspect the private phase journal and actual host state"
        ) from None
