"""scripts/sync_code_to_phone.py
Uploads updated Odysseus Python and JavaScript source files to the phone.
"""

import sys
import paramiko
from pathlib import Path

sys.path.insert(0, r"D:\ai_projects_2026\OdysseusWork")
from phone_connection import HOST, PORT, USER, PASSWORD, ROOTFS

LOCAL_AGENT_DIR = Path(r"D:\ai_projects_2026\OdysseusWork\odysseus-agent-1")
REMOTE_ODYSSEUS_DIR = f"{ROOTFS}/root/odysseus"

FILES_TO_SYNC = [
    "core/database.py",
    "src/projects_manager.py",
    "routes/projects/projects_routes.py",
    "static/js/projects.js",
]

print(f"Connecting to phone ({HOST}:{PORT})...")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=10)

sftp = c.open_sftp()
print("Uploading updated source files...")

for rel in FILES_TO_SYNC:
    local_path = LOCAL_AGENT_DIR / rel
    remote_path = f"{REMOTE_ODYSSEUS_DIR}/{rel}".replace("\\", "/")
    print(f"  {rel} -> {remote_path}")
    with open(local_path, "rb") as lf:
        sftp.putfo(lf, remote_path)

# Run status_reason migration on phone's app.db
migration_script = """import sqlite3
from pathlib import Path
db_path = Path('/data/data/com.termux/files/home/odysseus-data/app.db')
if db_path.exists():
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('PRAGMA table_info(projects)')
    cols = [r[1] for r in cur.fetchall()]
    if 'status_reason' not in cols:
        cur.execute('ALTER TABLE projects ADD COLUMN status_reason TEXT')
        conn.commit()
        print('Phone DB migrated: added status_reason column to projects')
    else:
        print('Phone DB already has status_reason column')
    conn.close()
"""
with sftp.file("/data/data/com.termux/files/home/migrate_status_reason.py", "w") as f:
    f.write(migration_script)
sftp.close()

_, stdout, stderr = c.exec_command("python3 /data/data/com.termux/files/home/migrate_status_reason.py ; rm -f /data/data/com.termux/files/home/migrate_status_reason.py")
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    print("STDERR:", err)

# Run full TestClient validation on phone
print("Validating live projects API endpoints on phone...")
test_script = """import sys
sys.path.insert(0, '/data/data/com.termux/files/usr/var/lib/proot-distro/containers/ubuntu/rootfs/root/odysseus')
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)
res = client.get('/api/projects')
print('GET /api/projects status:', res.status_code)
data = res.json()
print('Projects count:', len(data.get('items', [])))
first_p = data.get('items', [])[0]
print('First project:', first_p['name'], '| status:', first_p['status'], '| status_reason:', first_p.get('status_reason'))

# Test PUT status
put_res = client.put(f'/api/projects/{first_p[\"id\"]}', json={'status': 'on-hold', 'status_reason': 'Testing hold reason'})
print('PUT status response:', put_res.status_code)
print('Updated status:', put_res.json().get('project', {}).get('status'), '| reason:', put_res.json().get('project', {}).get('status_reason'))

# Test Summarize
sum_res = client.post(f'/api/projects/{first_p[\"id\"]}/summarize', json={})
print('POST summarize response:', sum_res.status_code)
print('Summary model used:', sum_res.json().get('model_used'))
print('Summary text:', sum_res.json().get('summary')[:80], '...')

# Reset to active
reset_res = client.put(f'/api/projects/{first_p[\"id\"]}', json={'status': 'active'})
print('Reset status:', reset_res.json().get('project', {}).get('status'), '| reason:', reset_res.json().get('project', {}).get('status_reason'))
"""

sftp2 = c.open_sftp()
with sftp2.file("/data/data/com.termux/files/home/test_proj_ep.py", "w") as f:
    f.write(test_script)
sftp2.close()

_, stdout, stderr = c.exec_command("python3 /data/data/com.termux/files/home/test_proj_ep.py ; rm -f /data/data/com.termux/files/home/test_proj_ep.py")
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    print("STDERR:", err)

c.close()
print("Sync, Migration & Verification complete!")
