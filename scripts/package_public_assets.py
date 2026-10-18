#!/usr/bin/env python3
"""Package verified public editor code after native installation checks."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from liberty.public_assets import REVIEWED, build_public_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apps", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest = build_public_manifest(args.apps, args.output)
    if set(manifest["apps"]) != set(REVIEWED):
        raise ValueError("The release must include every reviewed editor")
    print(
        "Verified public generation",
        manifest["generation"],
        "with",
        len(manifest["apps"]),
        "editors.",
    )


if __name__ == "__main__":
    main()
