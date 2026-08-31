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

sftp.close()
print("Source files transferred successfully.")

# Also test python import on phone
print("Validating python modules on phone...")
_, stdout, stderr = c.exec_command(
    "python3 -c \""
    "import sys; "
    "sys.path.insert(0, '/data/data/com.termux/files/usr/var/lib/proot-distro/containers/ubuntu/rootfs/root/odysseus'); "
    "from src.projects_manager import get_project_structure_and_spec; "
    "print('Imported get_project_structure_and_spec successfully!')\""
)
out = stdout.read().decode()
err = stderr.read().decode()
if out:
    print(out.strip())
if err:
    print("STDERR:", err.strip())

c.close()
print("Sync complete!")
