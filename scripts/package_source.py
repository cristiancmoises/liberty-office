#!/usr/bin/env python3
"""Create the AGPL source offer from a clean project/build context."""

import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
skip = {
    ".git",
    ".data",
    ".runtime",
    ".pytest_cache",
    ".superpowers",
    "__pycache__",
    ".venv",
    "node_modules",
    "acceptance-results",
    "playwright-report",
    "test-results",
}
private_docs = {"AGENTS.md", "RELEASE_REPORT.md", "CODE_REVIEW.md"}
out = Path(sys.argv[1])
with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if (
            any(x in skip or x in {"superpowers", "evidence"} for x in rel.parts)
            or p.name in private_docs
            or p.name.startswith("PROMPT")
            or p.name == ".env"
            or p.suffix == ".pyc"
            or p.resolve() == out.resolve()
        ):
            continue
        if p.is_file():
            z.write(p, arcname=str(rel))
print("Source offer generated.")
