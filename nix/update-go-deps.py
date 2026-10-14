#!/usr/bin/env python3
"""Refresh only the fixed-output Go vendor hash; fail closed on other errors."""

import argparse
import re
import subprocess
from pathlib import Path

FAKE_HASH = 'sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='


def hash_from_error(output: str) -> str:
    hashes = re.findall(r'\bgot:\s+(sha256-[A-Za-z0-9+/]{43}=)', output)
    if len(hashes) != 1:
        raise RuntimeError('Expected exactly one fixed-output hash mismatch; refusing to guess.\n' + output)
    return hashes[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate the current hash without editing it')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    path = root / 'nix/go-deps-hash.nix'
    command = ['nix', 'build', '--no-link', '--print-out-paths', f'path:{root}#go-modules']
    if args.check:
        subprocess.run(command, cwd=root, check=True)
        return
    original = path.read_text()
    try:
        path.write_text(f'# Updated by nix/update-go-deps.py after an upstream merge.\n"{FAKE_HASH}"\n')
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=900)
        if result.returncode == 0:
            raise RuntimeError('Unexpected successful build with a fake hash')
        actual = hash_from_error(result.stdout + '\n' + result.stderr)
        path.write_text(f'# Updated by nix/update-go-deps.py after an upstream merge.\n"{actual}"\n')
        subprocess.run(command, cwd=root, check=True, timeout=900)
    except BaseException:
        path.write_text(original)
        raise
    print(f'Go vendor hash: {actual}')


if __name__ == '__main__':
    main()
