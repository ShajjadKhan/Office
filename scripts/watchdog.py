#!/usr/bin/env python3
"""
OfficeWork & Infrastructure Autonomous Self-Healing Watchdog
Continuously monitors local services and public HTTPS endpoints.
If public access degrades or fails, automatically restores tunnels and services.
"""
import subprocess
import time
import sys
import os

SERVICES = [
    {
        "name": "OfficeWork",
        "local_url": "http://127.0.0.1:1212/login",
        "public_url": "https://officework.shajjadkhan.com/login",
        "app_service": "officework.service",
        "tunnel_service": "officework_tunnel.service",
    },
    {
        "name": "CyberNet ISP v2",
        "local_url": "http://127.0.0.1:9911/login",
        "public_url": "https://isp.shajjadkhan.com/login",
        "app_service": "isp_v2.service",
        "tunnel_service": "isp_tunnel.service",
    }
]

LOG_FILE = "/home/sk/officework/watchdog.log"

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {msg}"
    print(entry)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(entry + "\n")
    except Exception:
        pass

def check_http(url, timeout=7):
    cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", str(timeout), url]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        return res.stdout.strip()
    except subprocess.TimeoutExpired:
        return "timeout"
    except Exception as e:
        return f"err:{e}"

def has_internet():
    cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", "4", "https://1.1.1.1"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
        return res.stdout.strip() in ("200", "301", "302")
    except Exception:
        return False

def rotate_log():
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 500 * 1024:
            os.rename(LOG_FILE, LOG_FILE + ".1")
    except Exception:
        pass

def inspect_and_heal():
    rotate_log()

    for svc in SERVICES:
        name = svc["name"]
        local_url = svc["local_url"]
        public_url = svc["public_url"]
        app_service = svc["app_service"]
        tunnel_service = svc["tunnel_service"]

        # 1. Local App Health Check
        local_code = check_http(local_url, timeout=4)
        if local_code not in ("200", "302", "303"):
            log(f"ALERT [{name}]: Local service unresponsive ({local_url} returned '{local_code}'). Restarting {app_service}...")
            subprocess.run(["sudo", "systemctl", "restart", app_service])
            time.sleep(3)
            after_local = check_http(local_url, timeout=4)
            log(f"INFO [{name}]: {app_service} restarted (Local status: '{after_local}').")

        # 2. Public Endpoint Health Check
        pub_code = check_http(public_url, timeout=8)
        if pub_code in ("200", "302", "303"):
            # Healthy
            continue

        # Suspicious public failure; retry once after 5s to avoid transient network jitter
        log(f"WARN [{name}]: Public endpoint check failed with '{pub_code}'. Retrying in 5s...")
        time.sleep(5)
        retry_code = check_http(public_url, timeout=8)
        if retry_code in ("200", "302", "303"):
            log(f"INFO [{name}]: Public endpoint recovered on retry ('{retry_code}'). False alarm.")
            continue

        # If local machine itself has lost internet connection, wait rather than looping restarts
        if not has_internet():
            log(f"NOTICE [{name}]: Server appears to have no external internet connectivity. Skipping tunnel restart until WAN recovers.")
            continue

        # Self-heal tunnel
        log(f"HEAL [{name}]: Public endpoint failing (probe 1: '{pub_code}', probe 2: '{retry_code}'). Restarting {tunnel_service}...")
        subprocess.run(["sudo", "systemctl", "restart", tunnel_service])
        time.sleep(6)

        # Confirm post-heal status
        final_code = check_http(public_url, timeout=8)
        if final_code in ("200", "302", "303"):
            log(f"SUCCESS [{name}]: Public endpoint self-healed! Status: '{final_code}'.")
        else:
            log(f"WARN [{name}]: Public status after heal is '{final_code}'. Will re-evaluate on next cycle.")

    return 0

if __name__ == "__main__":
    try:
        sys.exit(inspect_and_heal() or 0)
    except Exception as e:
        log(f"Watchdog error: {e}")
        sys.exit(0)
