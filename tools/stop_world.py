"""Ask a running Olympus World to save and close (used by the installer before updating).

Usage: python stop_world.py "<install folder>"
Exit code 0 = nothing running now, 3 = a world is still running (older version: close it by hand).
Standalone on purpose: it runs before the new program files are copied in.
"""
import json
import os
import sys
import time
import urllib.request


def port_of(install_dir):
    try:
        with open(os.path.join(install_dir, "config", "settings.json"), "r", encoding="utf-8") as f:
            return int(json.load(f).get("port", 8788))
    except Exception:
        return 8788


def running(p):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{p}/api/state", timeout=2) as r:
            return bool(json.loads(r.read()).get("status", {}).get("version"))
    except Exception:
        return False


def main():
    install_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = port_of(install_dir)
    ports = [p for p in (base, base + 1) if running(p)]
    for p in ports:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{p}/api/shutdown", data=b"", method="POST",
                                         headers={"X-Olympus-Installer": "1"})
            urllib.request.urlopen(req, timeout=3).read()
        except Exception:
            pass
    for _ in range(10):
        if not any(running(p) for p in ports):
            print("not running")
            return 0
        time.sleep(0.5)
    print("still running")
    return 3


if __name__ == "__main__":
    sys.exit(main())
