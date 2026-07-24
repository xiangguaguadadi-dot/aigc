"""server-agent: execute commands on cloud server and print output."""
import paramiko
import sys
import io
import os

# Fix Windows GBK encoding issues
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

HOST = os.environ.get('A100_HOST', 'px-cloud1.matpool.com')
PORT = int(os.environ.get('A100_PORT', '27258'))
USER = os.environ.get('A100_USER', 'root')
PASSWORD = os.environ.get('A100_PASSWORD', '')

def run(cmd, timeout=120):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15)
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    print(out, flush=True)
    if err:
        print("[STDERR]", err, flush=True)
    ssh.close()
    return out, err

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python srv.py '<command>' [timeout]")
        sys.exit(1)
    cmd = sys.argv[1]
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    run(cmd, timeout)
