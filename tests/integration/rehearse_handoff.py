"""Execute the explicitly owned, loopback-only nginx/old-image qualification."""

from __future__ import annotations

import fcntl
import hashlib
import http.client
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from scripts.handoff import maintenance_handoff
from scripts.liberty_proxy import (
    ProcessIdentity,
    capture_workers,
    maintenance_config,
    process_exists,
    process_identity,
    wait_workers,
)

IMAGE = "sha256:bf0bd83d989308e935bc83ab0795a9db0cef1903e6cbd1802d3ccda2a93c96e9"
SCOPE = Path("/srv/liberty-free-use-20261017.hx8QEk")
SOURCE = SCOPE / "source"
ORIGINS = (
    "https://office.example.test",
    "https://editoffice.example.test",
    "https://demo-editoffice.example.test",
)


def docker(*args: str, **kwargs) -> str:
    return subprocess.check_output(["docker", *args], text=True, **kwargs).strip()


def inspect(container: str) -> dict:
    return json.loads(docker("inspect", container))[0]


def wait_for(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Synthetic fixture did not reach its expected state")
        time.sleep(0.025)


def request(path="/", method="GET", port=18880, host="office.example.test") -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, headers={"Host": host})
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def unlocked(data: Path) -> bool:
    with (data / "server.lock").open("rb") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(stream, fcntl.LOCK_UN)
        return True


class Rehearsal:
    def __init__(self, root: Path):
        self.root = root
        self.signals = root / "signals"
        self.containers: list[str] = []
        self.events: list[dict[str, object]] = []
        self.workers: list[ProcessIdentity] = []
        self.public_failures: list[str] = []
        self.public_checks = 0
        self.monitor_end = threading.Event()
        self.authority = root / "blue-data"
        self.receipt: dict[str, object] = {"nginx": "1.26.3", "old_image": IMAGE}

    def record(self, event):
        self.events.append({"event": event, "at": time.monotonic()})
        print(event, flush=True)

    def run_container(
        self,
        name,
        mounts,
        command,
        port=None,
        env=(),
        memory="192m",
        entrypoint="python",
    ):
        args = [
            "run",
            "-d",
            "--name",
            self.root.name + "-" + name,
            "--read-only",
            "--user",
            "10001:10001",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            memory,
            "--cpus",
            "0.5",
            "--pids-limit",
            "64",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=32m,mode=1777",
        ]
        if name == "nginx":
            args += ["--network", "host"]
        elif port:
            args += ["-p", f"127.0.0.1:{port}:8097"]
        else:
            args += ["--network", "none"]
        for source, target, readonly in mounts:
            args += [
                "--mount",
                f"type=bind,src={source},dst={target}"
                + (",readonly" if readonly else ""),
            ]
        for value in env:
            args += ["-e", value]
        args += ["--entrypoint", entrypoint, IMAGE, *command]
        container = docker(*args)
        self.containers.append(container)
        assert inspect(container)["Image"] == IMAGE
        return container

    def backend(self, name, data, port):
        return self.run_container(
            name,
            [
                (SOURCE / "tests/integration", "/fixture", True),
                (data, "/data", False),
                (self.signals, "/signals", False),
            ],
            [
                "-m",
                "uvicorn",
                "fixture_backend:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8097",
                "--workers",
                "1",
                "--timeout-keep-alive",
                "5",
                "--no-proxy-headers",
                "--no-access-log",
            ],
            port=port,
            env=[
                "PYTHONPATH=/fixture:/app",
                "LIBERTY_DATA=/data",
                "PUBLIC_ORIGIN=" + ORIGINS[0],
                "EDITOR_ORIGIN=" + ORIGINS[1],
                "DEMO_EDITOR_ORIGIN=" + ORIGINS[2],
            ],
        )

    def config(self, maintenance):
        # Independent private prefix: never includes /etc/nginx or live files.
        private = (
            "return 503;"
            if maintenance
            else "proxy_pass http://127.0.0.1:18897; proxy_request_buffering off;"
        )
        rendered = maintenance_config(
            portal="office.example.test",
            private="editoffice.example.test",
            demo="demo-editoffice.example.test",
            public_upstream="127.0.0.1:18898",
        )
        # Only isolated listeners change. All generated locations and directives
        # are interpreted by the real matching nginx runtime, not text assertions.
        rendered = rendered.replace("listen 80;", "listen 127.0.0.1:18882;").replace(
            "listen [::]:80;", ""
        )
        (self.root / "rendered.conf").write_text(rendered)
        text = """daemon off;
master_process on;
worker_processes 1;
pid /tmp/nginx.pid;
error_log stderr notice;
events { worker_connections 128; }
http {
 include /fixture/rendered.conf;
 access_log off;
 client_body_temp_path /tmp/client;
 proxy_temp_path /tmp/proxy;
 fastcgi_temp_path /tmp/fastcgi;
 scgi_temp_path /tmp/scgi;
 uwsgi_temp_path /tmp/uwsgi;
 proxy_next_upstream off;
 proxy_http_version 1.1;
 proxy_set_header Host $host;
 proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
 proxy_read_timeout 360s;
 proxy_send_timeout 360s;
 server {
  listen 127.0.0.1:18880;
  listen 127.0.0.1:18881 ssl;
  http2 on;
  ssl_certificate /fixture/cert.pem;
  ssl_certificate_key /fixture/key.pem;
  server_name office.example.test;
  client_max_body_size 1m;
  location /fixture/ { PRIVATE }
  location / { proxy_pass http://127.0.0.1:18898; }
 }
}
""".replace("PRIVATE", private)
        path = self.root / "nginx.conf.next"
        path.write_text(text)
        os.replace(path, self.root / "nginx.conf")

    def preflight(self):
        assert (
            self.root.parent == SCOPE / "build-storage"
            and self.root.name.startswith("handoff-m2-")
        )
        assert self.root.is_dir() and not self.root.is_symlink()
        assert (
            min(shutil.disk_usage(SCOPE).free, shutil.disk_usage(self.root).free)
            > 5 * 1024**3
        )
        # Never accept a production container by name, image alias or volume.
        live = inspect("liberty-office-office-1")
        assert (
            live["Id"]
            == "dc585651e301174b5a1b0fa0d4db753b9ba9f3407c9e29c21511859a298ea7a9"
        )
        assert (
            live["Image"] == IMAGE
            and live["State"]["Running"]
            and live["RestartCount"] == 0
        )
        assert not (self.root / "blue-data").exists(), (
            "Use a new fixture root for every run"
        )
        for name, want in json.loads((self.root / "nginx-runtime.json").read_text())[
            "files"
        ].items():
            assert (
                hashlib.sha256((self.root / "runtime" / name).read_bytes()).hexdigest()
                == want
            )
        for port in (18880, 18881, 18882, 18897, 18898, 18899):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
        for name in ("signals", "blue-data", "candidate-data"):
            folder = self.root / name
            folder.mkdir(mode=0o700)
            os.chown(folder, 10001, 10001)
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=liberty-synthetic-loopback",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
                "-keyout",
                str(self.root / "key.pem"),
                "-out",
                str(self.root / "cert.pem"),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        (self.root / "key.pem").chmod(
            0o644
        )  # Disposable fixture key; never an ingress credential.
        self.blue = self.backend("blue", self.root / "blue-data", 18897)
        wait_for(lambda: self.healthy(18897))
        self.public = self.run_container(
            "public",
            [
                (SOURCE, "/app", True),
                (
                    SCOPE / "build-storage/wordcraft-preview-01/apps",
                    "/opt/artcraft",
                    True,
                ),
                (
                    SCOPE / "build-storage/wordcraft-preview-01/public-assets",
                    "/public",
                    True,
                ),
            ],
            [
                "-m",
                "uvicorn",
                "liberty.public_app:create_public_app",
                "--factory",
                "--host",
                "0.0.0.0",
                "--port",
                "8097",
                "--workers",
                "1",
                "--no-proxy-headers",
                "--no-access-log",
            ],
            port=18898,
            env=[
                "PUBLIC_ORIGIN=" + ORIGINS[0],
                "EDITOR_ORIGIN=" + ORIGINS[1],
                "DEMO_EDITOR_ORIGIN=" + ORIGINS[2],
                "LIBERTY_DATA=/must-not-create-private-data",
                "LIBERTY_PUBLIC_ASSETS=/public",
            ],
        )
        wait_for(lambda: self.healthy(18898))
        self.config(False)
        loader = "/qual/lib64/ld-linux-x86-64.so.2"
        self.nginx = self.run_container(
            "nginx",
            [(self.root / "runtime", "/qual", True), (self.root, "/fixture", True)],
            [
                "--library-path",
                "/qual/lib/x86_64-linux-gnu",
                "/qual/usr/sbin/nginx",
                "-p",
                "/tmp/",
                "-c",
                "/fixture/nginx.conf",
                "-e",
                "stderr",
            ],
            memory="96m",
            entrypoint=loader,
        )
        wait_for(lambda: self.healthy(18880))
        self.qualify_rendered_routes()
        master = process_identity(inspect(self.nginx)["State"]["Pid"])
        assert master is not None
        self.master = master
        self.workers = capture_workers(self.master)
        self.keepalive = socket.create_connection(("127.0.0.1", 18880), timeout=5)
        self.keepalive.sendall(
            b"GET /healthz HTTP/1.1\r\nHost: office.example.test\r\nConnection: keep-alive\r\n\r\n"
        )
        self.idle_response = http.client.HTTPResponse(self.keepalive)
        self.idle_response.begin()
        assert self.idle_response.status == 200
        self.idle_response.read()
        self.long = socket.create_connection(("127.0.0.1", 18880), timeout=20)
        self.long.sendall(
            b"POST /fixture/write/long-upload HTTP/1.1\r\nHost: office.example.test\r\nContent-Length: 262144\r\n\r\n"
            + b"a" * 131072
        )
        self.disconnected = socket.create_connection(("127.0.0.1", 18880), timeout=5)
        self.disconnected.sendall(
            b"POST /fixture/write/disconnected HTTP/1.1\r\nHost: office.example.test\r\nContent-Length: 12\r\n\r\n"
            + b"disconnected"
        )
        wait_for(lambda: (self.signals / "disconnected.started").exists())
        self.disconnected.close()
        self.h2 = subprocess.Popen(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "host",
                "--read-only",
                "--user",
                "10001:10001",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "96m",
                "--cpus",
                "0.5",
                "--pids-limit",
                "32",
                "--mount",
                f"type=bind,src={self.signals},dst=/signals",
                "--mount",
                f"type=bind,src={SOURCE}/tests/integration/h2_retirement.mjs,dst=/client.mjs,readonly",
                "node:24-bookworm-slim",
                "node",
                "/client.mjs",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        wait_for(lambda: (self.signals / "h2-active.started").exists())
        self.monitor = threading.Thread(target=self.monitor_public)
        self.monitor.start()

    @staticmethod
    def healthy(port):
        try:
            return request("/healthz", port=port) == 200
        except (OSError, http.client.HTTPException):
            return False

    def monitor_public(self):
        while not self.monitor_end.is_set():
            for path in ("/", "/demo"):
                try:
                    if request(path) != 200:
                        self.public_failures.append(path)
                    self.public_checks += 1
                except (OSError, http.client.HTTPException):
                    self.public_failures.append(path)
            self.monitor_end.wait(0.1)

    def qualify_rendered_routes(self):
        asset = (
            "/public-assets/83f994359f52afdbeae393e15d2ae0988a1363ae2735ee6b275bc1e9e09fa390"
            "/wordcraft/wordcraft-web-8f83828293ff7c4d.js"
        )
        for path in ("/", "/demo"):
            assert request(path, port=18882) == 200
        assert request("/api/files", port=18882) == 503
        assert request("/", port=18882, host="editoffice.example.test") == 503
        for host in (
            "office.example.test",
            "editoffice.example.test",
            "demo-editoffice.example.test",
        ):
            assert request(asset, port=18882, host=host) == 200
        assert (
            request(
                asset, method="POST", port=18882, host="demo-editoffice.example.test"
            )
            == 405
        )
        assert request("/api/files", method="POST", port=18882) == 503
        self.receipt["rendered_routes_verified"] = True

    def enter_maintenance(self):
        self.config(True)
        # Test config using the same copied runtime; signal only our exact master.
        command = [
            "/qual/lib64/ld-linux-x86-64.so.2",
            "--library-path",
            "/qual/lib/x86_64-linux-gnu",
            "/qual/usr/sbin/nginx",
            "-p",
            "/tmp/",
            "-c",
            "/fixture/nginx.conf",
            "-t",
        ]
        docker("exec", self.nginx, *command, stderr=subprocess.DEVNULL)
        assert process_exists(self.master)
        os.kill(self.master.pid, signal.SIGHUP)
        wait_for(lambda: request("/fixture/admission") == 503)
        # This attests the new configuration, not retirement of old clients.
        assert request("/") == 200 and request("/demo") == 200

    def wait_old_proxy_workers(self):
        # Old idle HTTP1 and HTTP2 streams must retire, while an admitted upload
        # is allowed to finish on its original worker. Disconnected work outlives it.
        assert self.keepalive.recv(1) == b""
        self.keepalive.close()
        self.receipt["keepalive_retired"] = True
        wait_for(lambda: (self.signals / "h2.goaway").exists())
        self.receipt["http2_retired"] = True
        assert any(process_exists(worker) for worker in self.workers)
        self.long.sendall(b"b" * 131072)
        for name in ("long-upload", "h2-active"):
            (self.signals / (name + ".release")).touch()
        response = http.client.HTTPResponse(self.long)
        response.begin()
        assert response.status == 200
        assert json.loads(response.read())["mutation"] == "long-upload"
        self.long.close()
        assert self.h2.stdout is not None
        assert self.h2.wait(timeout=15) == 0, self.h2.stdout.read().decode()
        refusal = json.loads((self.signals / "h2.refused").read_text())
        assert refusal.get("rstCode") == 7 or refusal["code"] in {
            "ERR_HTTP2_GOAWAY_SESSION",
            "ERR_HTTP2_INVALID_SESSION",
        }
        wait_workers(self.workers)
        # Only the generation-exit boundary closes old admission completely.
        # Send this mutation once, never as a retrying readiness probe.
        assert request("/fixture/write/must-not-write", method="POST") == 503
        self.receipt["old_workers_exited"] = True
        assert not (self.signals / "disconnected.committed").exists()

    def graceful_stop_blue(self):
        self.receipt["lock_held_while_pending"] = not unlocked(self.authority)
        assert self.receipt["lock_held_while_pending"]
        self.stop = subprocess.Popen(
            ["docker", "container", "stop", "--time", "-1", self.blue],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.5)
        assert self.stop.poll() is None
        assert inspect(self.blue)["State"]["Running"]
        assert not unlocked(self.authority)
        (self.signals / "disconnected.release").touch()
        assert self.stop.wait(timeout=20) == 0
        state = inspect(self.blue)["State"]
        assert (
            not state["Running"]
            and not state["OOMKilled"]
            and state["Pid"] == 0
            and state["ExitCode"] == 0
        )
        self.receipt["old_process_exited"] = True
        self.receipt["lock_released_after_exit"] = unlocked(self.authority)
        assert self.receipt["lock_released_after_exit"]

    def reconcile(self):
        assert self.receipt["old_process_exited"] and unlocked(self.authority)
        # M2 synthetic copy only. Production reconciliation is the separately
        # qualified storage adapter, never this fixture or restore_backup.
        target = self.root / "candidate-data"
        shutil.copytree(self.authority, target, dirs_exist_ok=True)
        for file in target.rglob("*"):
            os.chown(file, 10001, 10001)
        self.authority = target

    def start_candidate(self):
        assert unlocked(self.authority)
        self.candidate = self.backend("candidate", self.authority, 18899)
        wait_for(lambda: self.healthy(18899))
        assert not unlocked(self.authority)

    def verify_candidate(self):
        with sqlite3.connect(self.authority / "fixture.db") as db:
            self.receipt["mutations"] = db.execute(
                "SELECT id,size FROM mutations ORDER BY id"
            ).fetchall()
        assert self.receipt["mutations"] == [
            ("disconnected", 12),
            ("h2-active", 9),
            ("long-upload", 262144),
        ]
        assert not (self.signals / "must-not-write.started").exists()

    def admit(self):
        # Qualification of production admission/rollback belongs to M4/M5.
        assert self.healthy(18899)

    def observe(self):
        assert request("/demo") == 200
        self.monitor_end.set()
        self.monitor.join(6)
        assert not self.public_failures
        assert self.public_checks >= 4
        self.receipt["public_checks"] = self.public_checks

    def restore_authoritative(self):
        # Never copy the stale blue fixture over a candidate. Leave an uncertain
        # run in maintenance, preserving both directories for investigation.
        raise RuntimeError("Preserve synthetic authorities for inspection")

    def close(self):
        self.monitor_end.set()
        if hasattr(self, "monitor"):
            self.monitor.join(6)
        if self.signals.exists():
            for name in (
                "long-upload",
                "disconnected",
                "h2-active",
                "must-not-write",
                "accepted-new",
            ):
                (self.signals / (name + ".release")).touch()
        for name in ("long", "disconnected", "keepalive"):
            if hasattr(self, name):
                getattr(self, name).close()
        for container in reversed(self.containers):
            if inspect(container)["State"]["Running"]:
                if container == getattr(self, "nginx", None):
                    docker("kill", "--signal", "QUIT", container)
                    docker("wait", container)
                else:
                    docker("container", "stop", "--time", "-1", container)


def main():
    rehearsal = Rehearsal(Path(sys.argv[1]))
    try:
        result = maintenance_handoff(rehearsal)
        rehearsal.receipt.update(result)
        rehearsal.receipt["public_failures"] = rehearsal.public_failures
        rehearsal.receipt["events"] = rehearsal.events
        (rehearsal.root / "receipt.json").write_text(
            json.dumps(rehearsal.receipt, sort_keys=True)
        )
    finally:
        rehearsal.close()


if __name__ == "__main__":
    main()
