"""fix_phone_owner.py
Updates all project records on phone SQLite to have owner=None so all users see them.
"""
import sqlite3
import sys
import paramiko

sys.path.insert(0, r"D:\ai_projects_2026\OdysseusWork")
from phone_connection import HOST, PORT, USER, PASSWORD, ROOTFS

print("Connecting to phone...")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=5)

cmd = (
    "python3 -c \""
    "import sqlite3; "
    "conn = sqlite3.connect('/data/data/com.termux/files/usr/var/lib/proot-distro/containers/ubuntu/rootfs/root/odysseus/data/app.db'); "
    "cur = conn.cursor(); "
    "cur.execute('UPDATE projects SET owner = NULL'); "
    "conn.commit(); "
    "print('Phone updated rows:', cur.rowcount); "
    "conn.close()\""
)

stdin, stdout, stderr = c.exec_command(cmd)
print(stdout.read().decode())
print(stderr.read().decode())
c.close()
