"""Keep private working notes out of the public source offer."""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/package_source.py"


@pytest.mark.parametrize(
    "private_name",
    [
        "docs/ACCEPTANCE.md",
        "docs/ACCEPTANCE.pt-BR.md",
        "docs/VALIDATION.md",
        "docs/VALIDATION.pt-BR.md",
        "docs/WORK_HANDOFF.md",
        "docs/private-delivery.md",
        "docs/nested/task.md",
        "docs/private-delivery.MD",
        "docs/private-delivery.mD",
        "prompt-local.md",
        "Prompt-local.MD",
        "my-prompt.md",
        "agents.md",
        "WORK_HANDOFF.md",
        "work_handoff.md",
        "Work_Handoff.MD",
        "release_report.md",
        "Release_Report.MD",
        "code_review.md",
        "Code_Review.MD",
    ],
)
def test_source_offer_excludes_local_working_notes(tmp_path, private_name):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    shutil.copyfile(SCRIPT, project / "scripts/package_source.py")
    note = project / private_name
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("Synthetic private delivery note.\n")
    public = {
        "README.md": "Public guide.\n",
        "docs/OPERATIONS.md": "Operator guide.\n",
        "docs/OPERATIONS.pt-BR.md": "Guia de operação.\n",
        "docs/SECURITY.md": "Security boundaries.\n",
        "docs/SECURITY.pt-BR.md": "Limites de segurança.\n",
        "docs/LICENSING.md": "Licensing conditions.\n",
        "docs/INTEGRITY.md": "Integrity verification.\n",
        "licenses/upstream/README.md": "Required upstream notice.\n",
        "server/prompts.mjs": "export const instruction = 'application feature';\n",
    }
    for name, content in public.items():
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    output = tmp_path / "source.zip"
    subprocess.run(
        [sys.executable, "-I", str(project / "scripts/package_source.py"), str(output)],
        cwd=project,
        env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    with zipfile.ZipFile(output) as archive:
        assert private_name not in archive.namelist()
        for name, content in public.items():
            assert archive.read(name).decode() == content
