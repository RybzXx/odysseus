"""scripts/pull_and_restart_phone.py
Pulls the latest Git commits on the Samsung Galaxy S24 Ultra and restarts all services.
"""

import sys
import time
import paramiko

sys.path.insert(0, r"D:\ai_projects_2026\OdysseusWork")
from phone_connection import HOST, PORT, USER, PASSWORD

print(f"Connecting to phone ({HOST}:{PORT})...")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=10)

print("\n--- Checking Git Remote & Branch on Phone ---")
commands = [
    "git -C /root/odysseus fetch origin local-agent-1",
    "git -C /root/odysseus reset --hard FETCH_HEAD",
    "git -C /root/odysseus log -1 --oneline",
]

for cmd in commands:
    proot_cmd = f"proot-distro login ubuntu -- bash -c '{cmd}'"
    print(f"\nExecuting: {cmd}")
    _, stdout, stderr = c.exec_command(proot_cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out:
        print(out.strip())
    if err:
        print("STDERR:", err.strip())

print("\n--- Restarting Odysseus and Dependent Services on Phone ---")
c.exec_command("pkill -9 -f uvicorn")
time.sleep(2)

_, stdout, _ = c.exec_command("bash /data/data/com.termux/files/home/.shortcuts/Start_All.sh")
print(stdout.read().decode())
time.sleep(4)

print("\n--- Verifying Active Processes ---")
_, stdout, _ = c.exec_command("ps aux | grep uvicorn")
print(stdout.read().decode())

c.close()
print("\nPull & Restart complete!")
