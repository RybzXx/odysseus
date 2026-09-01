"""scripts/sync_to_live_phone.py

Transfers all 21 project workspaces / manifests directly to the LIVE Odysseus runtime
on the Samsung Galaxy S24 Ultra (~/odysseus-data/projects/ and ~/odysseus-data/app.db).
"""

import json
import os
import sys
import posixpath
import paramiko
from datetime import datetime, timezone

# Add OdysseusWork to path to load connection config
sys.path.insert(0, r"D:\ai_projects_2026\OdysseusWork")
from phone_connection import HOST, PORT, USER, PASSWORD

sys.stdout.reconfigure(encoding="utf-8")

WORKSPACE_ROOT = r"D:\ai_projects_2026"
LIVE_DATA_DIR = "/data/data/com.termux/files/home/odysseus-data"
LIVE_PROJECTS_DIR = "/data/data/com.termux/files/home/odysseus-data/projects"
LIVE_APP_DB = "/data/data/com.termux/files/home/odysseus-data/app.db"


def sftp_mkdir_p(sftp, remote_directory):
    """Recursively create directories on the remote host."""
    if remote_directory in ("/", ""):
        return
    try:
        sftp.stat(remote_directory)
    except IOError:
        parent = posixpath.dirname(remote_directory.rstrip("/"))
        sftp_mkdir_p(sftp, parent)
        try:
            sftp.mkdir(remote_directory)
        except IOError:
            pass


def main():
    print(f"Connecting to Samsung Galaxy S24 Ultra ({HOST}:{PORT})...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=10)

    sftp = client.open_sftp()
    print("Connected via SFTP.")

    # 1. Ensure live projects root directory exists
    sftp_mkdir_p(sftp, LIVE_PROJECTS_DIR)

    # 2. Extract project definitions from local integration script
    sys.path.insert(0, r"D:\ai_projects_2026\OdysseusWork\odysseus-agent-1")
    from scripts.catalog_and_integrate import PROJECT_DEFINITIONS

    print(f"\n--- Transferring {len(PROJECT_DEFINITIONS)} Project Manifests to Live Phone Odysseus ---")
    synced_count = 0

    for proj in PROJECT_DEFINITIONS:
        folder = proj["folder"]
        slug = proj["slug"]
        local_manifest = os.path.join(WORKSPACE_ROOT, folder, "PROJECT.md")

        if not os.path.exists(local_manifest):
            print(f"[SKIP] Manifest not found: {local_manifest}")
            continue

        remote_project_dir = posixpath.join(LIVE_PROJECTS_DIR, slug)
        sftp_mkdir_p(sftp, remote_project_dir)
        sftp_mkdir_p(sftp, posixpath.join(remote_project_dir, "docs"))
        sftp_mkdir_p(sftp, posixpath.join(remote_project_dir, "tasks"))
        sftp_mkdir_p(sftp, posixpath.join(remote_project_dir, "logs"))

        remote_manifest = posixpath.join(remote_project_dir, "PROJECT.md")
        with open(local_manifest, "rb") as lf:
            sftp.putfo(lf, remote_manifest)
        synced_count += 1
        print(f"[SYNCED] {folder} -> ~/odysseus-data/projects/{slug}/PROJECT.md")

    sftp.close()

    # 3. Direct registration script executed via Termux Python into live app.db
    print("\n--- Registering Projects into Live Phone SQLite (app.db) ---")
    
    register_cmd = f"""python3 -c "
import os
import re
import uuid
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = '{LIVE_APP_DB}'
PROJECTS_DIR = Path('{LIVE_PROJECTS_DIR}')

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

folders = [d for d in PROJECTS_DIR.iterdir() if d.is_dir()]
print(f'Discovered {{len(folders)}} projects in {{PROJECTS_DIR}}')

now_iso = datetime.now(timezone.utc).isoformat()

for folder in sorted(folders, key=lambda x: x.name):
    manifest_path = folder / 'PROJECT.md'
    if not manifest_path.exists():
        continue
    
    raw_text = manifest_path.read_text(encoding='utf-8')
    
    # Parse YAML frontmatter
    slug = folder.name
    name = folder.name
    priority = 'normal'
    status = 'active'
    proj_id = f'proj_{{uuid.uuid4().hex[:8]}}'
    
    if raw_text.startswith('---'):
        parts = raw_text.split('---', 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ':' in line:
                    k, v = line.split(':', 1)
                    k, v = k.strip(), v.strip().strip('\\'').strip('\\"')
                    if k == 'id': proj_id = v
                    elif k == 'slug': slug = v
                    elif k == 'name': name = v
                    elif k == 'priority': priority = v
                    elif k == 'status': status = v

    # Parse checklist tasks
    tasks = []
    sort_order = 0
    for line in raw_text.splitlines():
        m = re.match(r'^\\s*[-*]\\s+\\[([ xX])\\]\\s+(.*)$', line)
        if m:
            tasks.append({{
                'completed': m.group(1).lower() == 'x',
                'title': m.group(2).strip(),
                'sort_order': sort_order
            }})
            sort_order += 1

    task_total = len(tasks)
    task_completed = sum(1 for t in tasks if t['completed'])

    # Check if project exists by slug
    cur.execute('SELECT id FROM projects WHERE slug = ?', (slug,))
    row = cur.fetchone()
    if row:
        proj_id = row[0]
        cur.execute('''
            UPDATE projects 
            SET name = ?, status = ?, priority = ?, owner = NULL,
                folder_path = ?, manifest_path = ?, task_total = ?, task_completed = ?,
                updated_at = ?
            WHERE id = ?
        ''', (name, status, priority, str(folder), str(manifest_path), task_total, task_completed, now_iso, proj_id))
    else:
        cur.execute('''
            INSERT INTO projects (id, slug, name, description, status, priority, owner, folder_path, manifest_path, task_total, task_completed, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
        ''', (proj_id, slug, name, name, status, priority, str(folder), str(manifest_path), task_total, task_completed, now_iso, now_iso))

    # Delete old tasks and insert fresh tasks
    cur.execute('DELETE FROM project_tasks WHERE project_id = ?', (proj_id,))
    for t in tasks:
        cur.execute('''
            INSERT INTO project_tasks (id, project_id, title, completed, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (f'ptask_{{uuid.uuid4().hex[:8]}}', proj_id, t['title'], 1 if t['completed'] else 0, t['sort_order'], now_iso, now_iso))

conn.commit()

cur.execute('SELECT COUNT(*) FROM projects')
total_p = cur.fetchone()[0]
cur.execute('SELECT COUNT(*) FROM project_tasks')
total_t = cur.fetchone()[0]

print(f'\\n=== Registration Complete ===')
print(f'Total Projects in ~/odysseus-data/app.db: {{total_p}}')
print(f'Total Tasks in ~/odysseus-data/app.db: {{total_t}}')

cur.execute('SELECT slug, name, task_completed, task_total, owner FROM projects ORDER BY updated_at DESC')
for r in cur.fetchall():
    print(f'  [{{r[0]}}] {{r[1]}} ({{r[2]}}/{{r[3]}} tasks) | owner={{r[4]}}')

conn.close()
" """

    stdin, stdout, stderr = client.exec_command(register_cmd)
    out = stdout.read().decode("utf-8")
    err = stderr.read().decode("utf-8")

    if out:
        print(out)
    if err:
        print("STDERR:", err)

    client.close()
    print("\n=== Live Phone Odysseus Fully Synchronized! ===")


if __name__ == "__main__":
    main()
