"""Real nginx/process/lock qualification; explicitly enabled on an owned fixture.

The orchestrator creates only synthetic directories and loopback-bound containers.
No production route, data volume or container is accepted by this harness.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("LIBERTY_HANDOFF_FIXTURE"),
    reason="Requires the explicitly provisioned remote synthetic fixture",
)
def test_exact_runtime_handoff_preserves_once_only_writes_and_public_delivery():
    root = Path(os.environ["LIBERTY_HANDOFF_FIXTURE"])
    assert root.name.startswith("handoff-m2-") and root.is_dir()
    assert not root.is_symlink()
    result = subprocess.run(
        ["python3", str(Path(__file__).with_name("rehearse_handoff.py")), str(root)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=240,
        check=False,
    )
    # Captured diagnostics contain synthetic identities only; no account secrets.
    assert result.returncode == 0, result.stdout
    receipt = json.loads((root / "receipt.json").read_text())
    assert receipt["nginx"] == "1.26.3"
    assert (
        receipt["old_image"]
        == "sha256:bf0bd83d989308e935bc83ab0795a9db0cef1903e6cbd1802d3ccda2a93c96e9"
    )
    assert receipt["old_workers_exited"] and receipt["old_process_exited"]
    assert receipt["lock_held_while_pending"] and receipt["lock_released_after_exit"]
    assert receipt["public_failures"] == []
    assert receipt["mutations"] == [
        ["disconnected", 12],
        ["h2-active", 9],
        ["long-upload", 262144],
    ]
    assert receipt["http2_retired"] and receipt["keepalive_retired"]
    assert receipt["rendered_routes_verified"]
    assert receipt["public_checks"] >= 4
