"""scripts/sync_to_phone.py

Transfers all 21 project workspaces / manifests to the Samsung Galaxy S24 Ultra
(running Odysseus inside proot Ubuntu) and registers them into the phone's SQLite app.db.
"""

import json
import os
import sys
import posixpath
import paramiko

# Add OdysseusWork to path to load connection config
sys.path.insert(0, r"D:\ai_projects_2026\OdysseusWork")
from phone_connection import HOST, PORT, USER, PASSWORD, ROOTFS

sys.stdout.reconfigure(encoding="utf-8")

WORKSPACE_ROOT = r"D:\ai_projects_2026"
LOCAL_CATALOG_SCRIPT = r"D:\ai_projects_2026\OdysseusWork\odysseus-agent-1\scripts\catalog_and_integrate.py"

PHONE_ODYSSEUS_ROOT = "/root/odysseus"
PHONE_DATA_DIR = "/root/odysseus/data"
PHONE_PROJECTS_DIR = "/root/odysseus/data/projects"

# Remote path as seen through Termux SFTP
SFTP_PROJECTS_DIR = ROOTFS + PHONE_PROJECTS_DIR


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
    print(f"Connecting to phone over Tailscale ({HOST}:{PORT})...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=10)

    sftp = client.open_sftp()
    print("Connected via SFTP.")

    # 1. Ensure projects root directory exists
    sftp_mkdir_p(sftp, SFTP_PROJECTS_DIR)

    # 2. Extract project definitions from local integration script
    sys.path.insert(0, r"D:\ai_projects_2026\OdysseusWork\odysseus-agent-1")
    from scripts.catalog_and_integrate import PROJECT_DEFINITIONS

    print(f"\n--- Transferring {len(PROJECT_DEFINITIONS)} Project Manifests to Phone ---")
    synced_count = 0

    for proj in PROJECT_DEFINITIONS:
        folder = proj["folder"]
        slug = proj["slug"]
        local_manifest = os.path.join(WORKSPACE_ROOT, folder, "PROJECT.md")

        if not os.path.exists(local_manifest):
            print(f"[SKIP] Manifest not found: {local_manifest}")
            continue

        remote_project_dir = posixpath.join(SFTP_PROJECTS_DIR, slug)
        sftp_mkdir_p(sftp, remote_project_dir)
        sftp_mkdir_p(sftp, posixpath.join(remote_project_dir, "docs"))
        sftp_mkdir_p(sftp, posixpath.join(remote_project_dir, "tasks"))
        sftp_mkdir_p(sftp, posixpath.join(remote_project_dir, "logs"))

        remote_manifest = posixpath.join(remote_project_dir, "PROJECT.md")
        content = open(local_manifest, "rb").read()
        sftp.putfo(open(local_manifest, "rb"), remote_manifest)
        synced_count += 1
        print(f"[SYNCED] {folder} -> {PHONE_PROJECTS_DIR}/{slug}/PROJECT.md")

    # 3. Create and push phone registration worker script
    phone_script_content = f"""# phone_db_register.py
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, "/root/odysseus")
from core.database import SessionLocal, Project, ProjectTask
from src.projects_manager import parse_tasks_from_markdown, parse_project_manifest

PROJECTS_DIR = Path("/root/odysseus/data/projects")
print("Scanning:", PROJECTS_DIR)

db = SessionLocal()
try:
    folders = [d for d in PROJECTS_DIR.iterdir() if d.is_dir()]
    print(f"Found {{len(folders)}} project folders on phone.")
    
    for folder in sorted(folders, key=lambda x: x.name):
        manifest_path = folder / "PROJECT.md"
        if not manifest_path.exists():
            continue
        
        raw_text = manifest_path.read_text(encoding="utf-8")
        metadata, body = parse_project_manifest(raw_text)
        tasks = parse_tasks_from_markdown(raw_text)
        
        slug = metadata.get("slug") or folder.name
        name = metadata.get("name") or folder.name
        status = metadata.get("status", "active")
        priority = metadata.get("priority", "normal")
        owner = metadata.get("owner")
        if owner == "default":
            owner = None
        
        task_total = len(tasks)
        task_completed = sum(1 for t in tasks if t.get("completed"))
        
        existing = db.query(Project).filter(Project.slug == slug).first()
        if existing:
            existing.name = name
            existing.status = status
            existing.priority = priority
            existing.folder_path = str(folder)
            existing.manifest_path = str(manifest_path)
            existing.task_total = task_total
            existing.task_completed = task_completed
            proj_id = existing.id
        else:
            proj_id = metadata.get("id") or f"proj_{{uuid.uuid4().hex[:8]}}"
            new_proj = Project(
                id=proj_id,
                slug=slug,
                name=name,
                description=name,
                status=status,
                priority=priority,
                owner=owner,
                folder_path=str(folder),
                manifest_path=str(manifest_path),
                task_total=task_total,
                task_completed=task_completed,
            )
            db.add(new_proj)
            
        db.query(ProjectTask).filter(ProjectTask.project_id == proj_id).delete()
        for t in tasks:
            db.add(ProjectTask(
                id=f"ptask_{{uuid.uuid4().hex[:8]}}",
                project_id=proj_id,
                title=t["title"],
                completed=t["completed"],
                sort_order=t["sort_order"],
            ))
            
    db.commit()
    print("\\n=== Phone SQLite Registration Complete ===")
    projs = db.query(Project).all()
    print(f"Total Projects in Phone Odysseus: {{len(projs)}}")
    for p in projs:
        print(f"  [{{p.slug}}] {{p.name}} ({{p.task_completed}}/{{p.task_total}} tasks)")
finally:
    db.close()
"""

    remote_worker_script = ROOTFS + "/root/odysseus/phone_db_register.py"
    with sftp.file(remote_worker_script, "w") as f:
        f.write(phone_script_content)

    sftp.close()
    print(f"\n[PUSHED] Phone registration worker -> /root/odysseus/phone_db_register.py")

    # 4. Run the worker script inside proot Ubuntu
    print("\n--- Executing Registration in Phone Ubuntu Container ---")
    exec_cmd = (
        'proot-distro login ubuntu -- bash -lc '
        '"cd /root/odysseus && /root/odysseus/venv/bin/python /root/odysseus/phone_db_register.py"'
    )
    stdin, stdout, stderr = client.exec_command(exec_cmd)
    out = stdout.read().decode("utf-8")
    err = stderr.read().decode("utf-8")

    if out:
        print(out)
    if err:
        clean_err = "\n".join([l for l in err.splitlines() if "can't sanitize binding" not in l])
        if clean_err.strip():
            print("STDERR:", clean_err)

    client.close()
    print("\n=== Phone Implementation Completed Successfully! ===")


if __name__ == "__main__":
    main()
