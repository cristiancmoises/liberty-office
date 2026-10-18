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
from http.cookies import SimpleCookie
from pathlib import Path

from scripts.handoff import HandoffError, maintenance_handoff
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
PASSWORD = "Liberty-test-password-42!"


class AccountClient:
    """Synthetic loopback client; never loads a real browser or account cookie."""

    def __init__(self, port, cookie=""):
        self.port, self.cookie = port, cookie

    def _request(
        self, path, method="GET", *, body=None, raw=None, headers=None
    ) -> tuple[str, bytes]:
        extra = {"Host": "office.example.test", "Origin": ORIGINS[0]}
        if self.cookie:
            extra["Cookie"] = self.cookie
            if method != "GET":
                extra["X-CSRF-Token"] = self.call("/api/auth/status")["csrf"]
        if body is not None:
            raw = json.dumps(body).encode()
            extra["Content-Type"] = "application/json"
        extra.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            connection.request(method, path, body=raw, headers=extra)
            response = connection.getresponse()
            content = response.read()
            assert response.status in (200, 201), (method, path, response.status)
            for name, value in response.getheaders():
                if name.lower() == "set-cookie":
                    cookie = SimpleCookie(value)
                    if "liberty_session" in cookie:
                        value = cookie["liberty_session"].value
                        self.cookie = "liberty_session=" + value if value else ""
            return response.getheader("Content-Type", ""), content
        finally:
            connection.close()

    def call(self, path, method="GET", *, body=None, raw=None, headers=None) -> dict:
        content_type, content = self._request(
            path, method, body=body, raw=raw, headers=headers
        )
        assert "application/json" in content_type
        value = json.loads(content)
        assert isinstance(value, dict)
        return value

    def download(self, path) -> bytes:
        return self._request(path)[1]

    def enroll(self):
        import pyotp

        setup = self.call("/api/auth/mfa/setup")
        return self.call(
            "/api/auth/mfa/verify",
            "POST",
            body={
                "code": pyotp.TOTP(setup["secret"]).now(),
            },
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
    def __init__(self, root: Path, failure: str | None = None):
        if failure not in (
            None,
            "candidate-start",
            "candidate-verify",
            "post-admission",
        ):
            raise ValueError("Unknown synthetic failure boundary")
        self.root = root
        self.failure = failure
        self.failure_injected = False
        self.signals = root / "signals"
        self.containers: list[str] = []
        self.events: list[dict[str, object]] = []
        self.workers: list[ProcessIdentity] = []
        self.public_failures: list[str] = []
        self.public_checks = 0
        self.monitor_end = threading.Event()
        self.authority = root / "blue-data"
        self.initial_drained = False
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

    def backend(self, name, data, port, *, current=False):
        mounts = [(SOURCE, "/app", True)] if current else []
        return self.run_container(
            name,
            mounts
            + [
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
                "DEFAULT_QUOTA_BYTES=100000000",
                "PUBLIC_SIGNUP_ENABLED=true",
                "MIN_FREE_BYTES=1073741824",
            ],
        )

    def config(self, maintenance, port=18897):
        # Independent private prefix: never includes /etc/nginx or live files.
        private = (
            "return 503;"
            if maintenance
            else f"proxy_pass http://127.0.0.1:{port}; proxy_request_buffering off;"
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
  location /api/ { PRIVATE }
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
        self.writer = self.blue
        wait_for(lambda: self.healthy(18897))
        self.seed_account()
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
        self.workers = capture_workers(self.master)
        self.config(True)
        self.reload_proxy()
        wait_for(lambda: request("/fixture/admission") == 503)
        # This attests the new configuration, not retirement of old clients.
        assert request("/") == 200 and request("/demo") == 200

    def reload_proxy(self, *, wait_retired=False):
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
        previous = capture_workers(self.master)
        os.kill(self.master.pid, signal.SIGHUP)
        if wait_retired:
            wait_workers(previous)

    def wait_old_proxy_workers(self):
        if self.initial_drained:
            wait_workers(self.workers)
            assert request("/fixture/write/must-not-write", method="POST") == 503
            return
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
        self.initial_drained = True

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
        target = self.root / "candidate-data"
        snapshot = self.storage_action("snapshot")
        assert snapshot["verified"] is True
        # The synthetic request gates use a separate, now-offline database.
        shutil.copyfile(self.authority / "fixture.db", target / "fixture.db")
        os.chown(target / "fixture.db", 10001, 10001)
        self.authority = target
        self.receipt["authoritative_snapshot_verified"] = True

    def start_candidate(self):
        assert unlocked(self.authority)
        self.fail_at("candidate-start")
        self.candidate = self.backend("candidate", self.authority, 18899, current=True)
        self.writer = self.candidate
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
        self.verify_account(18899)
        assert AccountClient(18899).call("/api/auth/status")["public_signup"] is True
        self.receipt["current_code_verified"] = True
        self.fail_at("candidate-verify")

    def admit(self):
        assert self.healthy(18899)
        self.config(False, port=18899)
        self.reload_proxy(wait_retired=True)
        wait_for(lambda: request("/fixture/admission") == 200)
        self.verify_account(18880)
        (self.signals / "accepted-new.release").touch()
        connection = http.client.HTTPConnection("127.0.0.1", 18880, timeout=10)
        try:
            connection.request(
                "POST",
                "/fixture/write/accepted-new",
                body=b"accepted-on-new",
                headers={"Host": "office.example.test"},
            )
            response = connection.getresponse()
            assert response.status == 200
            assert json.loads(response.read())["size"] == 15
        finally:
            connection.close()
        client = AccountClient(18880, self.account.cookie)
        self.accepted = client.call(
            "/api/files?name=accepted-new.txt", "POST", raw=b"accepted-on-new"
        )
        self.accepted_content = b"accepted-on-new"
        # This account is completed and recovered by the uninstrumented old code.
        self.public_account = AccountClient(18880)
        self.public_account.call(
            "/api/auth/signup",
            "POST",
            body={
                "username": "rollbackuser",
                "name": "Rollback User",
                "password": PASSWORD,
            },
        )
        self.fail_at("post-admission")

    def observe(self):
        self.qualify_rollback_and_repromotion()
        self.finish_public_monitor()

    def finish_public_monitor(self):
        assert request("/demo") == 200
        self.monitor_end.set()
        self.monitor.join(6)
        assert not self.public_failures
        assert self.public_checks >= 4
        self.receipt["public_checks"] = self.public_checks

    def fail_at(self, boundary):
        if self.failure == boundary:
            self.failure_injected = True
            raise RuntimeError("Synthetic failure at " + boundary)

    def seed_account(self):
        self.account = AccountClient(18897)
        self.account.call(
            "/api/auth/bootstrap",
            "POST",
            body={
                "token": (self.authority / "bootstrap-token").read_text().strip(),
                "username": "admin",
                "name": "Synthetic operator",
                "password": PASSWORD,
            },
        )
        self.account.enroll()
        self.first = self.account.call(
            "/api/files?name=history.txt", "POST", raw=b"old"
        )
        self.account.call(
            "/api/files/" + self.first["id"] + "/content",
            "PUT",
            raw=b"new",
            headers={"If-Match": self.first["etag"]},
        )
        self.account.call("/api/files/" + self.first["id"], "DELETE")
        self.key_hash = hashlib.sha256(
            (self.authority / "mfa.key").read_bytes()
        ).hexdigest()

    def verify_account(self, port):
        assert (
            hashlib.sha256((self.authority / "mfa.key").read_bytes()).hexdigest()
            == self.key_hash
        )
        client = AccountClient(port, self.account.cookie)
        status = client.call("/api/auth/status")
        assert status["state"] == "full" and status["user"]["quota"] == 100000000
        assert self.first["id"] in [
            row["id"] for row in client.call("/api/files?view=trash")["files"]
        ]
        client.call("/api/files/" + self.first["id"] + "/restore", "POST")
        assert client.download("/api/files/" + self.first["id"] + "/content") == b"new"
        assert (
            client.download(
                "/api/files/"
                + self.first["id"]
                + "/content?version="
                + self.first["version"]
            )
            == b"old"
        )
        client.call("/api/files/" + self.first["id"], "DELETE")

    def storage_action(self, action):
        commands = {
            "snapshot": "offline_snapshot(Path('/blue'),Path('/next'),Path('/backup/authoritative.tar.gz'))",
            "protect": "{'protected':protect_public_accounts(Path('/next'))}",
        }
        assert action in commands
        backup = self.root / "backup"
        if not backup.exists():
            backup.mkdir(mode=0o700)
            os.chown(backup, 10001, 10001)
        code = (
            "from pathlib import Path;import json;from scripts.liberty_storage import offline_snapshot,protect_public_accounts;print(json.dumps("
            + commands[action]
            + "))"
        )
        command = [
            "run",
            "--rm",
            "--read-only",
            "--network",
            "none",
            "--user",
            "10001:10001",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "256m",
            "--cpus",
            "0.5",
            "--pids-limit",
            "32",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=32m,mode=1777",
        ]
        for source, target in (
            (SOURCE, "/app"),
            (self.root / "blue-data", "/blue"),
            (
                self.root / "candidate-data"
                if action == "snapshot"
                else self.authority,
                "/next",
            ),
            (backup, "/backup"),
        ):
            command += [
                "--mount",
                f"type=bind,src={source},dst={target}"
                + (",readonly" if target == "/app" else ""),
            ]
        command += ["-w", "/app", "--entrypoint", "python", IMAGE, "-c", code]
        return json.loads(docker(*command))

    def stop_owner(self, container):
        docker("container", "stop", "--time", "-1", container)
        state = inspect(container)["State"]
        assert (
            not state["Running"]
            and state["Pid"] == 0
            and state["ExitCode"] == 0
            and not state["OOMKilled"]
        )
        assert unlocked(self.authority)

    def qualify_rollback_and_repromotion(self):
        self.enter_maintenance()
        self.wait_old_proxy_workers()
        self.stop_owner(self.candidate)
        assert self.storage_action("protect")["protected"] == 1
        self.rollback = self.backend("rollback", self.authority, 18899)
        self.writer = self.rollback
        wait_for(lambda: self.healthy(18899))
        assert not unlocked(self.authority)
        self.verify_account(18899)
        client = AccountClient(18899, self.account.cookie)
        assert (
            client.download("/api/files/" + self.accepted["id"] + "/content")
            == b"accepted-on-new"
        )
        # Complete MFA using old code, then use a recovery code to return to enroll.
        self.public_account.port = 18899
        recovery = self.public_account.enroll()["recovery_codes"][0]
        self.public_account.call("/api/auth/logout", "POST")
        self.public_account.call(
            "/api/auth/login",
            "POST",
            body={"username": "rollbackuser", "password": PASSWORD},
        )
        assert (
            self.public_account.call(
                "/api/auth/mfa/verify", "POST", body={"code": recovery}
            )["state"]
            == "enroll"
        )
        client.call(
            "/api/files/" + self.accepted["id"] + "/content",
            "PUT",
            raw=b"accepted-on-old",
            headers={"If-Match": self.accepted["etag"]},
        )
        self.accepted_content = b"accepted-on-old"
        self.receipt["rollback_preserved_accepted_writes"] = True
        self.stop_owner(self.rollback)
        # Synthetic expired account demonstrates cleanup protection on re-promotion.
        with sqlite3.connect(self.authority / "liberty.db") as db:
            db.execute(
                "UPDATE public_accounts SET created_at=1 WHERE user_id IN (SELECT id FROM users WHERE username='rollbackuser')"
            )
            db.execute("UPDATE users SET created=1 WHERE username='rollbackuser'")
        self.repromoted = self.backend(
            "repromoted", self.authority, 18899, current=True
        )
        self.writer = self.repromoted
        wait_for(lambda: self.healthy(18899))
        assert not unlocked(self.authority)
        self.verify_account(18899)
        assert (
            client.download("/api/files/" + self.accepted["id"] + "/content")
            == b"accepted-on-old"
        )
        assert self.public_account.call("/api/auth/status")["state"] == "enroll"
        AccountClient(18899).call(
            "/api/auth/signup",
            "POST",
            body={
                "username": "cleanupcheck",
                "name": "Cleanup check",
                "password": PASSWORD,
            },
        )
        self.public_account.enroll()
        with sqlite3.connect(self.authority / "liberty.db") as db:
            row = db.execute(
                "SELECT u.quota,p.cleanup_protected FROM users u JOIN public_accounts p ON p.user_id=u.id WHERE u.username='rollbackuser'"
            ).fetchone()
            assert row == (100000000, 1)
        with sqlite3.connect(self.authority / "fixture.db") as db:
            assert db.execute(
                "SELECT id,size FROM mutations WHERE id='accepted-new'"
            ).fetchall() == [("accepted-new", 15)]
        self.config(False, port=18899)
        self.reload_proxy(wait_retired=True)
        wait_for(lambda: request("/fixture/admission") == 200)
        assert (
            AccountClient(18880, self.account.cookie).download(
                "/api/files/" + self.accepted["id"] + "/content"
            )
            == b"accepted-on-old"
        )
        self.receipt["repromotion_preserved_accounts"] = True

    def restore_authoritative(self):
        # The source is the current authoritative filesystem, never blue's stale
        # copy. Prove every fixture owner exited before starting old code on it.
        owners = [
            container
            for container in self.containers
            if inspect(container)["State"]["Running"]
            and any(
                mount["Destination"] == "/data"
                and mount["RW"]
                and Path(mount["Source"]).resolve() == self.authority.resolve()
                for mount in inspect(container)["Mounts"]
            )
        ]
        assert len(owners) <= 1
        if owners:
            assert owners == [self.writer]
            self.stop_owner(self.writer)
        assert unlocked(self.authority)
        self.storage_action("protect")
        self.recovery = self.backend("recovery", self.authority, 18899)
        self.writer = self.recovery
        wait_for(lambda: self.healthy(18899))
        assert not unlocked(self.authority)
        self.verify_account(18899)
        if hasattr(self, "accepted"):
            assert (
                AccountClient(18899, self.account.cookie).download(
                    "/api/files/" + self.accepted["id"] + "/content"
                )
                == self.accepted_content
            )
            with sqlite3.connect(self.authority / "fixture.db") as db:
                assert db.execute(
                    "SELECT id,size FROM mutations WHERE id='accepted-new'"
                ).fetchall() == [("accepted-new", 15)]
            self.receipt["accepted_write_preserved"] = True
        self.receipt["recovery_authority"] = self.authority.name
        self.receipt["recovery_verified"] = True
        assert request("/api/files") == 503

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
    rehearsal = Rehearsal(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else None)
    try:
        try:
            result = maintenance_handoff(rehearsal)
        except HandoffError:
            if (
                not rehearsal.failure_injected
                or rehearsal.receipt.get("recovery_verified") is not True
            ):
                raise
            assert request("/api/files") == 503
            assert request("/fixture/admission") == 503
            rehearsal.finish_public_monitor()
            result = {
                "phase": "recovered",
                "accounts": "maintenance",
                "failure_mode": rehearsal.failure,
            }
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
