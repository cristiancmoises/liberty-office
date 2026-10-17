import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from liberty.app import create_app
from liberty.config import Settings


def cli(tmp_path, language, *args):
    env = {
        **os.environ,
        "LIBERTY_DATA": str(tmp_path / "data"),
        "PUBLIC_ORIGIN": "http://localhost:8097",
        "LANG": "pt_BR.UTF-8",
    }
    env.pop("LIBERTY_CLI_LANGUAGE", None)
    if language is not None:
        env["LIBERTY_CLI_LANGUAGE"] = language
    return subprocess.run(
        [sys.executable, "-m", "liberty.cli", *args],
        env=env,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    "language,pt", [(None, False), ("pt-BR", True), ("invalid", False)]
)
def test_cli_language_help_error_and_token_protocol(tmp_path, language, pt):
    help_result = cli(tmp_path, language, "--help")
    assert help_result.returncode == 0
    assert (
        "Comandos locais" if pt else "Local operator commands"
    ) in help_result.stdout.decode()
    result = cli(tmp_path, language, "backup")
    assert result.returncode == 1 and result.stdout == b""
    assert result.stderr.decode().strip() == (
        "Erro: Informe um caminho de saída ou --stdout."
        if pt
        else "Error: Provide an output path or --stdout."
    )
    data = tmp_path / "data"
    data.mkdir()
    token = "synthetic-token-Senha-123"
    (data / "bootstrap-token").write_text(token)
    result = cli(tmp_path, language, "bootstrap-token")
    assert result.returncode == 0 and result.stderr == b""
    assert result.stdout == (token + "\n").encode()
    assert not (data / "liberty.db").exists()
    (data / "bootstrap-token").unlink()
    result = cli(tmp_path, language, "bootstrap-token")
    assert result.stdout.decode().strip() == (
        "Configuração inicial já concluída."
        if pt
        else "Initial setup is already complete."
    )


@pytest.mark.parametrize("language,pt", [(None, False), ("pt-BR", True)])
def test_cli_backup_binary_stdout_and_status_json(tmp_path, language, pt):
    settings = Settings(
        data_dir=tmp_path / "data",
        apps_dir=tmp_path / "apps",
        origin="http://localhost:8097",
    )
    with TestClient(create_app(settings)):
        pass
    result = cli(tmp_path, language, "backup", "--stdout")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(b"\x1f\x8b")
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:gz") as archive:
        assert {"BACKUP.json", "liberty.db", "mfa.key"} <= set(archive.getnames())
    assert result.stderr.decode().strip() == (
        "Backup concluído com banco, arquivos, versões e chave MFA."
        if pt
        else "Backup completed with database, files, revisions, and MFA key."
    )
    status = cli(tmp_path, language, "status")
    assert status.returncode == 0 and status.stderr == b""
    assert set(json.loads(status.stdout)) == {
        "version",
        "users",
        "data_bytes",
        "installed_apps",
    }


def test_cli_translates_only_known_messages_and_validated_backup_prefix(monkeypatch):
    from liberty.cli import cli_text

    monkeypatch.setenv("LIBERTY_CLI_LANGUAGE", "en")
    assert cli_text("Conta ativa não encontrada.") == "Active account not found."
    assert (
        cli_text("SHA-256 inválido no backup: mfa.key")
        == "Invalid SHA-256 in backup: mfa.key"
    )
    arbitrary = "SHA-256 inválido no backup: /private/Meu documento.txt"
    assert cli_text(arbitrary) == arbitrary
    monkeypatch.setenv("LIBERTY_CLI_LANGUAGE", "pt-BR")
    assert cli_text("Conta ativa não encontrada.") == "Conta ativa não encontrada."


def test_cli_unknown_error_keeps_path_verbatim(tmp_path, monkeypatch, capsys):
    from liberty import cli as commands

    monkeypatch.setenv("LIBERTY_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("LIBERTY_CLI_LANGUAGE", "en")
    monkeypatch.setattr(sys, "argv", ["liberty.cli", "backup", "unused"])
    message = "[Errno 13] Permission denied: '/private/Arquivo não encontrado./Nome'"

    def fail(*args):
        raise OSError(message)

    monkeypatch.setattr(commands, "make_backup", fail)
    monkeypatch.chdir(tmp_path)
    assert commands.main() == 1
    assert capsys.readouterr().err == "Error: " + message + "\n"


@pytest.mark.parametrize(
    "language,pt", [(None, False), ("pt-BR", True), ("unexpected", False)]
)
def test_launcher_language_and_compose_forwarding(tmp_path, language, pt):
    root = Path(__file__).resolve().parents[1]
    shutil.copy2(root / "libertyctl", tmp_path / "libertyctl")
    original_config = b"PUBLIC_ORIGIN=https://unchanged.example\n"
    (tmp_path / ".env").write_bytes(original_config)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\nimport json,os,sys\n"
        "with open(os.environ['DOCKER_CALLS'],'a') as log: log.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "if 'bootstrap-token' in sys.argv: print('synthetic-token')\n"
        "if 'backup' in sys.argv: sys.stdout.buffer.write(b'\\x1f\\x8bsynthetic-backup')\n"
    )
    docker.chmod(0o700)
    calls = tmp_path / "calls.jsonl"
    env = {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "DOCKER_CALLS": str(calls),
        "LANG": "pt_BR.UTF-8",
    }
    env.pop("LIBERTY_CLI_LANGUAGE", None)
    if language is not None:
        env["LIBERTY_CLI_LANGUAGE"] = language

    def run(*args):
        return subprocess.run(
            ["./libertyctl", *args],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    help_result = run()
    assert help_result.returncode == 0
    assert ("Uso:" if pt else "Usage:") in help_result.stdout
    error = run("up", "invalid")
    assert error.returncode == 1
    assert ("Origem inválida." if pt else "Invalid origin.") in error.stderr
    token = run("token")
    assert (
        token.returncode == 0
        and token.stdout == "synthetic-token\n"
        and token.stderr == ""
    )
    recovery = run("recover", "synthetic-user")
    assert recovery.returncode == 0
    for command in ("status", "verify"):
        assert run(command).returncode == 0
    backup_path = tmp_path / "snapshot.gz"
    assert run("backup", str(backup_path)).returncode == 0
    assert backup_path.read_bytes() == b"\x1f\x8bsynthetic-backup"
    invocations = [json.loads(line) for line in calls.read_text().splitlines()]
    expected_language = "LIBERTY_CLI_LANGUAGE=" + ("pt-BR" if pt else "en")
    for command in ("bootstrap-token", "recover", "status", "doctor", "backup"):
        invocation = next(args for args in invocations if command in args)
        assert invocation[invocation.index("-e") + 1] == expected_language
    assert ["compose", "stop", "office"] in invocations
    assert ["compose", "up", "-d", "office"] in invocations
    assert (tmp_path / ".env").read_bytes() == original_config
