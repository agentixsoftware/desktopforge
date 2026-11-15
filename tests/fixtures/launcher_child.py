"""Trusted test subprocess: no compositor, shell, systemd or network interaction."""
import json
import os
from pathlib import Path
import signal
import sys
import time

mode, ready = sys.argv[1:3]
if mode == 'ignore-term':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
config_content = None
if mode == 'read-config':
    config_content = Path(os.environ['NIRI_CONFIG']).read_text()
Path(ready).write_text(json.dumps({'config_content': config_content, 'pid': os.getpid(), 'sid': os.getsid(0),
                                 'config': os.environ.get('NIRI_CONFIG'),
                                 'unrelated': os.environ.get('UNRELATED')}))
if mode in ('exit', 'read-config'):
    raise SystemExit(7)
while True:
    time.sleep(1)
