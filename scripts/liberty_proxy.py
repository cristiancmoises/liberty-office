"""Scoped nginx rendering and real Linux worker-generation retirement."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    start_ticks: int


def process_identity(pid: int, proc: Path = Path("/proc")) -> ProcessIdentity | None:
    if pid <= 1:
        raise ValueError("Expected an explicit non-init process")
    try:
        fields = (proc / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        return ProcessIdentity(pid, int(fields[19]))
    except FileNotFoundError:
        return None
    except (IndexError, ValueError):
        raise RuntimeError("Cannot establish process identity") from None


def process_exists(identity: ProcessIdentity, proc: Path = Path("/proc")) -> bool:
    return process_identity(identity.pid, proc) == identity


def capture_workers(
    master: ProcessIdentity, proc: Path = Path("/proc")
) -> list[ProcessIdentity]:
    if not process_exists(master, proc):
        raise RuntimeError("The pinned nginx master changed")
    workers = []
    for entry in proc.iterdir():
        if not entry.name.isdecimal() or int(entry.name) <= 1:
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            command = (entry / "cmdline").read_bytes()
            if int(fields[1]) == master.pid and any(
                part.startswith(b"nginx: worker process")
                for part in command.split(b"\0")
            ):
                workers.append(ProcessIdentity(int(entry.name), int(fields[19])))
        except FileNotFoundError:
            continue
    if not workers:
        raise RuntimeError("No nginx workers were captured; do not infer retirement")
    if not process_exists(master, proc):
        raise RuntimeError("The nginx master changed during capture")
    return sorted(workers, key=lambda item: item.pid)


def wait_workers(
    workers: Iterable[ProcessIdentity],
    *,
    proc: Path = Path("/proc"),
    pause: Callable[[float], object] = time.sleep,
) -> None:
    pending = set(workers)
    if not pending:
        raise ValueError("An explicit captured generation is required")
    # No forced shutdown deadline. PID reuse is not the old worker generation.
    while pending:
        pending = {worker for worker in pending if process_exists(worker, proc)}
        if pending:
            pause(0.25)


def maintenance_config(
    *, portal: str, private: str, demo: str, public_upstream: str
) -> str:
    hosts = (portal, private, demo)
    if len(set(hosts)) != 3 or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host) for host in hosts
    ):
        raise ValueError("Expected three distinct exact DNS hosts")
    if not re.fullmatch(
        r"(?:127\.0\.0\.1|192\.168\.1\.54):[1-9][0-9]{3,4}", public_upstream
    ):
        raise ValueError("Expected the scoped Liberty upstream")
    if int(public_upstream.rsplit(":", 1)[1]) > 65535:
        raise ValueError("Invalid upstream port")
    template = (
        Path(__file__).parents[1] / "deploy/nginx.liberty-maintenance.conf"
    ).read_text()
    for token, value in zip(
        ("PORTAL_HOST", "PRIVATE_HOST", "DEMO_HOST", "PUBLIC_UPSTREAM"),
        (*hosts, public_upstream),
    ):
        template = template.replace("@" + token + "@", value)
    return template
