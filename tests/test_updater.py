import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from olympus_world import updater

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_release(version, broken=False, extra=None, drop=None):
    """A GitHub-style zip of this program with a different version number."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for d in ("olympus_world", "web", "tools", "tests"):
            for dirpath, dirnames, files in os.walk(os.path.join(ROOT, d)):
                dirnames[:] = [x for x in dirnames if x != "__pycache__"]
                for fn in files:
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
                    if drop and rel == drop:
                        continue
                    data = open(full, "rb").read()
                    if broken and rel == "olympus_world/world.py":
                        data += b"\ndef oops(:\n"
                    z.writestr("olympus-world-main/" + rel, data)
        z.writestr("olympus-world-main/version.json", json.dumps({"version": version, "notes": "new things"}))
        z.writestr("olympus-world-main/update.json", json.dumps({"repo": "SnookC/olympus-world", "branch": "main"}))
        z.writestr("olympus-world-main/config/settings.json", '{"port": 1}')
        z.writestr("olympus-world-main/config/secrets.env", "GEMINI_API_KEY=FROM_GITHUB")
        z.writestr("olympus-world-main/data/world.json", "{}")
        for k, v in (extra or {}).items():
            z.writestr("olympus-world-main/" + k, v)
    return buf.getvalue()


class FakeGitHub:
    def __init__(self):
        self.version = {"version": "9.9.9", "notes": "new things"}
        self.zip = make_release("9.9.9")
        gh = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if "/version.json" in self.path:
                    body = json.dumps(gh.version).encode()
                elif "/zip/" in self.path:
                    body = gh.zip
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class TestUpdater(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub()
        self.old = (updater.RAW_BASE, updater.ZIP_BASE)
        updater.RAW_BASE = updater.ZIP_BASE = self.gh.base
        # an installed copy of the program, with the owner's private things
        self.root = tempfile.mkdtemp()
        for d in ("olympus_world", "web", "tools", "tests"):
            shutil.copytree(os.path.join(ROOT, d), os.path.join(self.root, d),
                            ignore=shutil.ignore_patterns("__pycache__"))
        with open(os.path.join(self.root, "version.json"), "w") as f:
            json.dump({"version": "1.2.0"}, f)
        with open(os.path.join(self.root, "update.json"), "w") as f:
            json.dump({"repo": "SnookC/olympus-world", "branch": "main"}, f)
        os.makedirs(os.path.join(self.root, "config"))
        os.makedirs(os.path.join(self.root, "data"))
        with open(os.path.join(self.root, "config", "settings.json"), "w") as f:
            f.write('{"port": 8788, "web_daily_cap": 7}')
        with open(os.path.join(self.root, "config", "secrets.env"), "w") as f:
            f.write("GEMINI_API_KEY=MINE")
        with open(os.path.join(self.root, "data", "world.json"), "w") as f:
            f.write('{"the": "gods world"}')
        with open(os.path.join(self.root, "olympus_world", "old_leftover.py"), "w") as f:
            f.write("x = 1\n")

    def tearDown(self):
        updater.RAW_BASE, updater.ZIP_BASE = self.old
        self.gh.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def read(self, *p):
        with open(os.path.join(self.root, *p), "r", encoding="utf-8") as f:
            return f.read()

    def test_version_compare(self):
        self.assertTrue(updater.newer("1.10.0", "1.9.9"))
        self.assertFalse(updater.newer("1.2.0", "1.2.0"))
        self.assertTrue(updater.newer("2", "1.9"))

    def test_check_finds_newer_and_ignores_same(self):
        self.assertEqual(updater.check(self.root)["version"], "9.9.9")
        self.gh.version = {"version": "1.2.0"}
        self.assertIsNone(updater.check(self.root))

    def test_check_off_without_repo(self):
        with open(os.path.join(self.root, "update.json"), "w") as f:
            json.dump({"repo": ""}, f)
        self.assertIsNone(updater.check(self.root))

    def test_install_keeps_owner_things_and_backs_up(self):
        updater.install("9.9.9", say=lambda m: None, root=self.root)
        self.assertEqual(updater.current_version(self.root), "9.9.9")
        self.assertIn("MINE", self.read("config", "secrets.env"))
        self.assertIn("web_daily_cap", self.read("config", "settings.json"))
        self.assertIn("gods world", self.read("data", "world.json"))
        self.assertFalse(os.path.exists(os.path.join(self.root, "olympus_world", "old_leftover.py")))
        backups = os.listdir(os.path.join(self.root, "backups"))
        self.assertEqual(len(backups), 1)
        b = os.path.join(self.root, "backups", backups[0])
        self.assertTrue(os.path.exists(os.path.join(b, "olympus_world", "old_leftover.py")))
        self.assertIn("1.2.0", open(os.path.join(b, "version.json")).read())

    def test_broken_update_is_refused_and_nothing_changes(self):
        self.gh.zip = make_release("9.9.9", broken=True)
        before = self.read("olympus_world", "world.py")
        with self.assertRaises(updater.UpdateError) as cm:
            updater.install("9.9.9", say=lambda m: None, root=self.root)
        self.assertIn("world.py", str(cm.exception))
        self.assertEqual(self.read("olympus_world", "world.py"), before)
        self.assertEqual(updater.current_version(self.root), "1.2.0")

    def test_wrong_version_or_not_olympus_refused(self):
        self.gh.zip = make_release("9.9.8")
        with self.assertRaises(updater.UpdateError):
            updater.install("9.9.9", say=lambda m: None, root=self.root)
        self.gh.zip = make_release("9.9.9", drop="olympus_world/server.py")
        with self.assertRaises(updater.UpdateError):
            updater.install("9.9.9", say=lambda m: None, root=self.root)
        self.assertEqual(updater.current_version(self.root), "1.2.0")

    def test_unsafe_paths_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("top/version.json", '{"version":"9.9.9"}')
            z.writestr("top/../../evil.py", "x")
        self.gh.zip = buf.getvalue()
        with self.assertRaises(updater.UpdateError):
            updater.install("9.9.9", say=lambda m: None, root=self.root)

    def test_missing_repo_message(self):
        self.gh.version = None
        updater.RAW_BASE = self.gh.base + "/nothing-here"
        with self.assertRaises(updater.UpdateError):
            updater.check(self.root)


if __name__ == "__main__":
    unittest.main()
