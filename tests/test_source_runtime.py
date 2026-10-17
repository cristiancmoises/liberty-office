import json

from scripts import check_runtime


def test_runtime_uses_each_editor_build_lock_and_checks_assets(
    env, tmp_path, monkeypatch
):
    _, _, settings = env
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(
        check_runtime, "__file__", str(repository / "scripts/check_runtime.py")
    )
    apps = [
        {"id": "figcraft", "version": "v0.6.0"},
        {"id": "gridcraft", "version": "v0.7.0"},
    ]
    (repository / "upstream.lock.json").write_text(json.dumps({"apps": apps}))
    for app in apps:
        directory = settings.apps_dir / app["id"]
        directory.mkdir(parents=True)
        (directory / "index.html").write_text("editor")
        (directory / "installed.json").write_text(
            json.dumps({**app, "files": {"index.html": "0" * 64}})
        )
    calls = []

    def reviewed(record, lock):
        calls.append((record["id"], lock))
        return True

    monkeypatch.setattr(check_runtime, "source_build_matches", reviewed)
    report = check_runtime.inspect(settings)
    assert calls == [
        (app["id"], repository / (app["id"] + "-build.lock.json")) for app in apps
    ]
    assert all(
        c["ok"] and "Pinned source build" in c["detail"]
        for c in report["checks"]
        if c["name"].startswith("app:")
    )
    deep = check_runtime.inspect(settings, deep=True)
    assert all(not c["ok"] for c in deep["checks"] if c["name"].startswith("app:"))
