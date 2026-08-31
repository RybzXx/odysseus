"""scripts/remove_qa_project.py
Removes the QA Verification Project from both PC and Phone SQLite databases and filesystems.
"""

import sys
import shutil
import sqlite3
import paramiko
from pathlib import Path

LOCAL_AGENT_DIR = Path(r"D:\ai_projects_2026\OdysseusWork\odysseus-agent-1")
LOCAL_DB = LOCAL_AGENT_DIR / "data" / "app.db"

sys.path.insert(0, r"D:\ai_projects_2026\OdysseusWork")
from phone_connection import HOST, PORT, USER, PASSWORD, ROOTFS

# 1. Clean PC
print("--- Cleaning PC Database and Disk ---")
conn = sqlite3.connect(LOCAL_DB)
cur = conn.cursor()
cur.execute("SELECT id, slug, name FROM projects WHERE slug LIKE '%qa%' OR name LIKE '%QA%' OR slug LIKE '%widget%'")
rows = cur.fetchall()
print("PC Matching rows to remove:", rows)
for r in rows:
    pid = r[0]
    cur.execute("DELETE FROM project_tasks WHERE project_id = ?", (pid,))
    cur.execute("DELETE FROM project_links WHERE project_id = ?", (pid,))
    cur.execute("DELETE FROM notes WHERE project_id = ?", (pid,))
    cur.execute("DELETE FROM projects WHERE id = ?", (pid,))
    print(f"Deleted project {r[1]} ({pid}) from PC SQLite.")
conn.commit()
conn.close()

for folder_name in ["qa-verification-project", "widget-live-validation"]:
    p_dir = LOCAL_AGENT_DIR / "data" / "projects" / folder_name
    if p_dir.exists():
        shutil.rmtree(p_dir)
        print(f"Removed local directory: {p_dir}")

# 2. Clean Phone
print("\n--- Cleaning Phone Database and Disk ---")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=10)

sftp = c.open_sftp()

# We can directly run python via a temp script file to avoid escaping issues
remote_cleanup_script = "/data/data/com.termux/files/home/clean_qa.py"
script_content = """import sqlite3, shutil
from pathlib import Path

db_path = Path("/data/data/com.termux/files/home/odysseus-data/app.db")
if db_path.exists():
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, slug, name FROM projects WHERE slug LIKE '%qa%' OR name LIKE '%QA%' OR slug LIKE '%widget%'")
    rows = cur.fetchall()
    print("Phone rows to delete:", rows)
    for r in rows:
        pid = r[0]
        cur.execute("DELETE FROM project_tasks WHERE project_id = ?", (pid,))
        cur.execute("DELETE FROM project_links WHERE project_id = ?", (pid,))
        cur.execute("DELETE FROM notes WHERE project_id = ?", (pid,))
        cur.execute("DELETE FROM projects WHERE id = ?", (pid,))
        print(f"Deleted {r[1]} ({pid}) from Phone DB")
    conn.commit()
    conn.close()

for f in ["qa-verification-project", "widget-live-validation"]:
    f_path = Path(f"/data/data/com.termux/files/home/odysseus-data/projects/{f}")
    if f_path.exists():
        shutil.rmtree(f_path)
        print(f"Removed phone directory: {f_path}")
"""

with sftp.file(remote_cleanup_script, "w") as f:
    f.write(script_content)
sftp.close()

_, stdout, stderr = c.exec_command(f"python3 {remote_cleanup_script} && rm {remote_cleanup_script}")
out = stdout.read().decode()
err = stderr.read().decode()
if out:
    print(out.strip())
if err:
    print("Phone STDERR:", err.strip())

# Verify total count on phone
_, stdout, _ = c.exec_command(
    "python3 -c \""
    "import sqlite3; "
    "conn = sqlite3.connect('/data/data/com.termux/files/home/odysseus-data/app.db'); "
    "cur = conn.cursor(); "
    "cur.execute('SELECT slug FROM projects ORDER BY slug'); "
    "projs = [r[0] for r in cur.fetchall()]; "
    "print(f'Active projects remaining on phone ({len(projs)}):', projs); "
    "conn.close()\""
)
print("\n" + stdout.read().decode().strip())

c.close()
print("\nQA Verification Project removed completely from all environments!")
