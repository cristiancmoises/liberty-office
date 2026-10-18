"""Keep the candidate version consistent across runtime and operator entrypoints."""

from pathlib import Path

import pytest

from liberty import __version__

ROOT = Path(__file__).parents[1]
CANDIDATE = "0.2.0-rc.2"


def test_runtime_uses_the_qualified_candidate_version():
    assert __version__ == CANDIDATE


@pytest.mark.parametrize(
    "name",
    [
        "compose.yaml",
        "libertyctl",
        "scripts/docker_acceptance.sh",
        "README.md",
        "README.pt-BR.md",
        "docs/ACCEPTANCE.md",
        "docs/ACCEPTANCE.pt-BR.md",
        "docs/OPERATIONS.md",
        "docs/OPERATIONS.pt-BR.md",
    ],
)
def test_current_release_entrypoints_name_the_candidate(name):
    assert CANDIDATE in (ROOT / name).read_text()
