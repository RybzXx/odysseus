"""Deploy an exact phone revision. Validate by default; --apply requires a verified backup."""
import argparse
import json
from pathlib import Path
import shlex
import sys
import time
import paramiko


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--source", default="origin", help="Remote or phone-side bundle")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if len(args.commit) != 40 or any(c not in "0123456789abcdef" for c in args.commit):
        parser.error("--commit requires an exact lowercase commit ID")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from phone_connection import HOST, PORT, USER, PASSWORD, ROOTFS
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=10)

    def guest(command):
        _, out, err = client.exec_command("proot-distro login ubuntu -- bash -c " + shlex.quote(command), timeout=90)
        stdout, stderr = out.read().decode(), err.read().decode()
        if out.channel.recv_exit_status():
            raise RuntimeError(stderr or stdout)
        return stdout

    try:
        with client.open_sftp() as sftp:
            sftp.put(str(Path(__file__).with_name("deploy_revision.py")), ROOTFS + "/tmp/odysseus-deploy-revision.py")
        check = "import json,pathlib; p=pathlib.Path(" + repr(args.backup) + "); d=json.loads((p/'verified.json').read_text()); assert d.get('database_integrity')=='ok'; assert (p/'app.db').is_file()"
        guest("python3 -c " + shlex.quote(check))
        if args.apply:
            # A bundle advertises HEAD. Its ancestors remain selectable by exact ID.
            fetch_ref = "HEAD" if args.source.endswith(".bundle") else args.commit
            guest("git -C /root/odysseus fetch -- " + shlex.quote(args.source) + " " + fetch_ref)
        command = "python3 /tmp/odysseus-deploy-revision.py --repo /root/odysseus --commit " + args.commit
        print(guest(command + (" --apply" if args.apply else "")))
        if args.apply:
            # Match the Python module arguments, never a broad process-name pattern.
            stop = """import pathlib,os,signal,json
pids=[]
for p in pathlib.Path('/proc').iterdir():
    if not p.name.isdigit():
        continue
    try:
        if b'-m\\x00uvicorn\\x00app:app\\x00' in p.joinpath('cmdline').read_bytes():
            os.kill(int(p.name), signal.SIGTERM)
            pids.append(int(p.name))
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        continue
print(json.dumps(pids))
"""
            old_pids = json.loads(guest("python3 -c " + shlex.quote(stop)))
            # The existing supervisor owns startup.
            for _ in range(24):
                time.sleep(5)
                try:
                    probe = ("import pathlib,urllib.request; "
                             + "assert not any(pathlib.Path('/proc',str(p)).exists() for p in " + repr(old_pids) + "); "
                             + "r=urllib.request.urlopen('http://127.0.0.1:7000/api/health',timeout=3); assert r.status==200")
                    guest("python3 -c " + shlex.quote(probe))
                    print(json.dumps({"liveness": "passed", "commit": args.commit}))
                    return
                except RuntimeError:
                    continue
            raise RuntimeError("Odysseus did not become live within two minutes. Inspect the supervisor.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
