"""scripts/inspect_models.py
Inspects model endpoints on PC and Phone.
"""

import sys
import sqlite3
import paramiko
from pathlib import Path

LOCAL_AGENT_DIR = Path(r"D:\ai_projects_2026\OdysseusWork\odysseus-agent-1")
LOCAL_DB = LOCAL_AGENT_DIR / "data" / "app.db"

sys.path.insert(0, r"D:\ai_projects_2026\OdysseusWork")
from phone_connection import HOST, PORT, USER, PASSWORD

print("=== PC Model Endpoints ===")
conn = sqlite3.connect(LOCAL_DB)
cur = conn.cursor()
cur.execute("SELECT id, name, url, endpoint_kind, pinned_models, enabled FROM model_endpoints")
rows = cur.fetchall()
print(f"Total endpoints on PC: {len(rows)}")
for r in rows:
    print(r)
conn.close()

print("\n=== Phone Model Endpoints ===")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=5)

sftp = c.open_sftp()
script = """import sqlite3
conn = sqlite3.connect('/data/data/com.termux/files/home/odysseus-data/app.db')
cur = conn.cursor()
cur.execute('SELECT id, name, url, endpoint_kind, pinned_models, enabled FROM model_endpoints')
rows = cur.fetchall()
print('Total endpoints on Phone:', len(rows))
for r in rows:
    print(r)
conn.close()
"""
with sftp.file("/data/data/com.termux/files/home/query_models.py", "w") as f:
    f.write(script)
sftp.close()

_, stdout, stderr = c.exec_command("python3 /data/data/com.termux/files/home/query_models.py && rm /data/data/com.termux/files/home/query_models.py")
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    print("STDERR:", err)
c.close()
