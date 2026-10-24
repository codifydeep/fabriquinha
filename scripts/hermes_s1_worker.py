"""Deterministic fixture process for S1, executed without network or credentials."""
import hashlib
import json
import os
import socket
from pathlib import Path
import sys
import time

mode, scenario, host_database = sys.argv[1:]
file = Path('/work/product.txt')
checks = dict(host_database_absent=not Path(host_database).exists(),
              docker_socket_absent=not Path('/var/run/docker.sock').exists(),
              secret_mount_absent=not Path('/secret').exists(),
              provider_key_absent=not any(k in os.environ for k in
                  ('OPENROUTER_API_KEY', 'GH_TOKEN', 'GITHUB_TOKEN', 'TELEGRAM_BOT_TOKEN')))
try:
    connection = socket.create_connection(('1.1.1.1', 53), timeout=0.5)
    connection.close()
    checks['external_network_denied'] = False
except OSError:
    checks['external_network_denied'] = True
if scenario == 'hold':
    time.sleep(90)  # Deliberate live fixture for capacity/crash tests only.
if mode == 'review':
    before = file.read_bytes()
    try:
        file.write_bytes(b'forbidden review write')
        checks['review_write_denied'] = False
    except OSError:
        checks['review_write_denied'] = file.read_bytes() == before
    action = 'approve' if before == b'version two\n' else 'changes'
else:
    existed = file.exists()
    file.write_bytes(b'version two\n' if file.exists() else b'version one\n')
    file.chmod(0o666)
    if scenario == 'crash-once' and not existed:
        os._exit(23)  # Preserve the real write and exercise native crash recovery.
    action = 'finish' if scenario == 'leaf' else 'review'
print(json.dumps(dict(isolation=checks, result=dict(action=action,
    sha=hashlib.sha256(file.read_bytes()).hexdigest()))), flush=True)
