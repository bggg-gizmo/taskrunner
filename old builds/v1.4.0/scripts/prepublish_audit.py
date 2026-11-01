"""Offline best-effort scan for private data and costly GitHub Actions before publishing.

This is a guardrail, not a proof that a repository contains no secrets.
"""
from __future__ import annotations
import argparse
import os
import re
from pathlib import Path

SKIP_DIRS={'.git','__pycache__','.pytest_cache','.venv','venv','dist','build','.idea'}
SENSITIVE_SUFFIXES={'.sqlite3','.db','.pem','.p12','.pfx','.key','.jks','.keystore','.ovpn'}
PATTERNS={
    'GitHub access token':re.compile(r'(?:ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}'),
    'Private key block':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'AWS access key':re.compile(r'AKIA[0-9A-Z]{16}'),
}
TEXT_SUFFIXES={'.py','.md','.txt','.yml','.yaml','.json','.cmd','.bat','.toml','.gitignore','.gitattributes','.editorconfig'}


def audit(root:Path) -> list[str]:
    root=Path(root).resolve()
    violations=[]
    for base, dirs, files in os.walk(root):
        dirs[:]=sorted(x for x in dirs if x not in SKIP_DIRS)
        for name in sorted(files):
            path=Path(base)/name
            rel=path.relative_to(root)
            posix=rel.as_posix()
            if path.is_symlink():
                violations.append(f'{posix}: symlink requires manual review')
                continue
            if name=='.env' or name.startswith('.env.') or path.suffix.lower() in SENSITIVE_SUFFIXES:
                violations.append(f'{posix}: private-data / signing filename')
            if posix.startswith('.github/workflows/') and path.suffix in ('.yml','.yaml'):
                violations.append(f'{posix}: GitHub Actions workflow forbidden by project cost policy')
            if path.stat().st_size>30*1024*1024:
                violations.append(f'{posix}: unexpectedly large file ({path.stat().st_size} bytes)')
            if path.suffix.lower() in TEXT_SUFFIXES or name in ('.gitignore','.gitattributes','.editorconfig'):
                if path.stat().st_size>5*1024*1024:
                    continue
                try:source=path.read_text(encoding='utf-8')
                except UnicodeError:
                    violations.append(f'{posix}: non-UTF-8 text file needs inspection')
                    continue
                for label,pattern in PATTERNS.items():
                    if pattern.search(source):
                        violations.append(f'{posix}: possible {label}; review locally without posting it')
    return violations


def main():
    parser=argparse.ArgumentParser(description='Offline Task Runner pre-publication audit')
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
    options=parser.parse_args()
    errors=audit(options.root)
    if errors:
        print(f'FAIL: {len(errors)} pre-publication concern(s) found:')
        for problem in errors:print('  -',problem)
        return 1
    print('PASS: no obvious private files, token signatures or GitHub Actions workflows detected.')
    print('Manual staged-diff review and GitHub secret scanning are still required.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
