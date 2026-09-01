"""inspect_live_phone_db.py"""
import sys
import paramiko

sys.path.insert(0, r"D:\ai_projects_2026\OdysseusWork")
from phone_connection import HOST, PORT, USER, PASSWORD

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=5)

cmd = """python3 -c "
import sqlite3
conn = sqlite3.connect('/data/data/com.termux/files/home/odysseus-data/app.db')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM projects')
print('Projects in ~/odysseus-data/app.db:', cur.fetchone()[0])
cur.execute('SELECT slug, name, owner FROM projects')
for row in cur.fetchall():
    print(' ', row)
conn.close()
" """

stdin, stdout, stderr = c.exec_command(cmd)
print(stdout.read().decode())
print(stderr.read().decode())
c.close()
