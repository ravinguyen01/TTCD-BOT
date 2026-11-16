"""Inspect staged Git blobs without printing potential credential values."""
from pathlib import PurePosixPath
import re
import subprocess
import sys


def git(*args):
    result=subprocess.run(['git',*args],capture_output=True,check=True)
    return result.stdout


paths=[p.decode('utf-8') for p in git('ls-files','--cached','-z').split(b'\0') if p]
if not paths:
    raise SystemExit('No staged files to inspect')
patterns=[
    ('private key',re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),
    ('service account key',re.compile(rb'"private_key"\s*:\s*"[^"\r\n]{20,}')),
    ('GitHub token',re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{40,})')),
    ('Discord token',re.compile(rb'[A-Za-z0-9_-]{23,28}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{25,}')),
    ('populated bot token setting',re.compile(rb'^BOT_TOKEN[ \t]*=[ \t]*[^\s#][^\r\n]*',re.MULTILINE)),
]
errors=[]
for path in paths:
    parts=PurePosixPath(path).parts
    forbidden=(any(p in {'plebot','__pycache__','.venv','backups','artifacts'} for p in parts)
               or (parts[0]=='secrets' and path!='secrets/.gitkeep')
               or (PurePosixPath(path).name.startswith('.env') and path!='.env.example')
               or PurePosixPath(path).suffix.lower() in {'.dump','.backup','.sqlite3','.pem','.key','.log','.pyc'})
    if forbidden:
        errors.append((path,'excluded/private/generated file'))
        continue
    content=git('show',':'+path)
    for reason,pattern in patterns:
        if pattern.search(content):
            errors.append((path,reason))
    try:
        content.decode('utf-8')
    except UnicodeDecodeError:
        errors.append((path,'unexpected binary file'))
if errors:
    for path,reason in errors:
        print(f'BLOCKED {path}: {reason}',file=sys.stderr)
    raise SystemExit(1)
print(f'PASS: inspected {len(paths)} staged UTF-8 files; excluded data and credential patterns not found.')
