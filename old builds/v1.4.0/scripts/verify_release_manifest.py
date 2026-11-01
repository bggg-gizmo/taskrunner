"""Verify a complete Task Runner source tree against its release manifest."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
EXCLUDED={'RELEASE_FILE_MANIFEST.json'}


def sha256(path):
    d=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1<<20),b''):d.update(chunk)
    return d.hexdigest()


def verify(root=ROOT):
    root=Path(root)
    manifest=json.loads((root/'RELEASE_FILE_MANIFEST.json').read_text('utf-8'))
    for relative,record in manifest['files'].items():
        file=root/relative
        if not file.is_file() or file.is_symlink():
            raise ValueError(f'Missing file or symlink in release: {relative}')
        if file.stat().st_size!=record['bytes'] or sha256(file)!=record['sha256']:
            raise ValueError(f'Changed release file: {relative}')
    print(f"PASS: {len(manifest['files'])} public files verified against SHA-256 manifest")
    return True


if __name__=='__main__':verify()
