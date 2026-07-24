"""server-agent: execute multi-line commands on cloud server."""
import paramiko
import sys
import os

HOST = os.environ.get('A100_HOST', 'px-cloud1.matpool.com')
PORT = int(os.environ.get('A100_PORT', '27258'))
USER = os.environ.get('A100_USER', 'root')
PASSWORD = os.environ.get('A100_PASSWORD', '')

def run(code, timeout=120):
    """Write code to remote /tmp/_srv.py and execute it."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=15)

    # Write the script
    escaped = code.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
    cmd = f'cat > /tmp/_srv.py << "PYEOF"\n{code}\nPYEOF\npython3 /tmp/_srv.py'
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
        print("Usage: python srv_exec.py '<python_code>' [timeout]")
        sys.exit(1)
    code = sys.argv[1]
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    run(code, timeout)
