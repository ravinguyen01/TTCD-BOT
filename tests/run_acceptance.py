"""Run acceptance checks against a disposable database, never the live DB."""
import asyncio
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
database = urlsplit(os.environ.get('DATABASE_URL', '')).path.lstrip('/')
if not re.fullmatch(r'classbot_acceptance_[0-9_]+', database):
    raise SystemExit('Refusing acceptance tests: use a disposable classbot_acceptance_<timestamp> database.')


async def initialize():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    try:
        await conn.execute((ROOT/'classbot'/'schema.sql').read_text(encoding='utf-8'))
        for migration in sorted((ROOT/'classbot'/'migrations').glob('*.sql')):
            await conn.execute(migration.read_text(encoding='utf-8'))
    finally:
        await conn.close()


asyncio.run(initialize())
environment = {**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONIOENCODING': 'utf-8'}
files = ['test_mock.py', 'test_notices.py', 'test_onboarding.py', 'test_roster_names.py',
         'test_roster_refresh.py', 'test_accounts.py']
for name in files:
    print(f'RUN {name}', flush=True)
    result = subprocess.run([sys.executable, str(ROOT/'tests'/name)], env=environment, cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)
print(f'ACCEPTANCE PASS: {len(files)} test groups; isolated schema and migrations verified.', flush=True)
