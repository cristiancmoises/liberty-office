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
    ".ruff_cache",
    ".mypy_cache",
    ".superpowers",
    "__pycache__",
    ".venv",
    "node_modules",
    "acceptance-results",
    "playwright-report",
    "test-results",
}
private_docs = {"agents.md", "release_report.md", "code_review.md", "work_handoff.md"}
public_docs = {
    "docs/OPERATIONS.md",
    "docs/OPERATIONS.pt-BR.md",
    "docs/SECURITY.md",
    "docs/SECURITY.pt-BR.md",
    "docs/LICENSING.md",
    "docs/INTEGRITY.md",
}
out = Path(sys.argv[1])
with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if (
            any(x in skip or x in {"superpowers", "evidence"} for x in rel.parts)
            or p.name.casefold() in private_docs
            or (p.suffix.casefold() == ".md" and "prompt" in p.stem.casefold())
            or (
                rel.parts[0] == "docs"
                and p.suffix.lower() == ".md"
                and rel.as_posix() not in public_docs
            )
            or p.name == ".env"
            or p.suffix == ".pyc"
            or p.resolve() == out.resolve()
        ):
            continue
        if p.is_file():
            z.write(p, arcname=str(rel))
print("Source offer generated.")
