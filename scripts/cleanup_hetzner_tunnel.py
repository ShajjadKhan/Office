#!/usr/bin/env python3
import subprocess
import os

SSH_KEY = "/home/sk/.ssh/id_hetzner_tunnel"
REMOTE = "shajjad@135.181.39.96"
TARGET_PORT = "1212"

def check_and_clean():
    if not os.path.exists(SSH_KEY):
        return

    # 1. Check if TARGET_PORT is listening on Hetzner
    cmd_ss = [
        "ssh", "-i", SSH_KEY,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=3",
        "-o", "StrictHostKeyChecking=accept-new",
        REMOTE, f"ss -tulpn | grep :{TARGET_PORT}"
    ]
    try:
        res_ss = subprocess.run(cmd_ss, capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        print("[cleanup] ss check timed out.")
        return

    if not res_ss.stdout.strip():
        print(f"[cleanup] Port {TARGET_PORT} is free on Hetzner.")
        return

    # 2. Test if TARGET_PORT responds to HTTP GET on Hetzner
    cmd_curl = [
        "ssh", "-i", SSH_KEY,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=3",
        REMOTE, f"curl -s -o /dev/null -w '%{{http_code}}' -m 3 http://127.0.0.1:{TARGET_PORT}/login"
    ]
    try:
        res_curl = subprocess.run(cmd_curl, capture_output=True, text=True, timeout=5)
        code = res_curl.stdout.strip()
    except subprocess.TimeoutExpired:
        print("[cleanup] curl check timed out.")
        code = "timeout"

    if code in ("200", "302"):
        print(f"[cleanup] Port {TARGET_PORT} is healthy (HTTP {code}).")
    else:
        print(f"[cleanup] Port {TARGET_PORT} returned '{code}' (zombie socket). Clearing stale sessions...")
        cmd_kill = [
            "ssh", "-i", SSH_KEY,
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=3",
            REMOTE, "pkill -u shajjad -f 'sshd-session: shajjad$' || true"
        ]
        try:
            subprocess.run(cmd_kill, capture_output=True, text=True, timeout=5)
            print("[cleanup] Stale sessions cleared on Hetzner.")
        except subprocess.TimeoutExpired:
            print("[cleanup] pkill timed out.")

if __name__ == "__main__":
    try:
        check_and_clean()
    except Exception as e:
        print(f"[cleanup] Warning: {e}")
