import os
from pathlib import Path
import subprocess
import sys
for name, value in list(os.environ.items()):
    if name.endswith('_FILE'):
        os.environ[name[:-5]] = Path(value).read_text(encoding='utf-8').strip()
subprocess.run([sys.executable, 'manage.py', 'migrate', '--noinput'], check=True)
os.execvp('gunicorn', ['gunicorn', 'mj_backend.wsgi:application', '--bind', '0.0.0.0:8000', '--workers', '2', '--timeout', '60'])
