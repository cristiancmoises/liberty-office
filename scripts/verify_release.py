#!/usr/bin/env python3
"""Verify the source manifest of an extracted release, without executing its code."""
import argparse,hashlib,re,sys
from pathlib import Path

def verify(root):
    root=Path(root).resolve();checked=0
    for line in (root/'MANIFEST.sha256').read_text().splitlines():
        match=re.fullmatch(r'([0-9a-f]{64})  (.+)',line)
        if not match:raise ValueError('Invalid manifest line')
        expected,name=match.groups();path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise ValueError('Missing or unsafe path: '+name)
        with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
        if actual!=expected:raise ValueError('SHA-256 mismatch: '+name)
        checked+=1
    if checked==0:raise ValueError('Empty manifest')
    return checked

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root',nargs='?',default=Path(__file__).resolve().parents[1]);args=parser.parse_args()
    try:print('Verified',verify(args.root),'source files.');return 0
    except (OSError,ValueError) as error:print(str(error),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
