"""Runs the world and serves the watch-only 3D viewer at http://127.0.0.1:<port>.

Only your own PC can open the viewer (it listens on 127.0.0.1).
"""
import argparse
import json
import subprocess
import mimetypes
import os
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import VERSION, updater
from .brains import FakeBrain, GeminiBrain, OllamaBrain, Router, UsageLedger
from .config import DEFAULT_DATA_DIR, WEB_DIR, load_secrets, load_settings
from .mind import Engine
from .world import World

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")


class App:
    def __init__(self, data_dir, settings, fake=False, search_fn=None, gemini=True):
        os.makedirs(data_dir, exist_ok=True)
        self.settings = settings
        self.world = World(data_dir, settings)
        ledger = UsageLedger(os.path.join(data_dir, "usage.json"))
        if fake:
            local = FakeBrain()
            gem = None
        else:
            local = OllamaBrain(settings["ollama_url"], settings["local_model"])
            key = load_secrets().get("GEMINI_API_KEY") if gemini else None
            gem = GeminiBrain(key, settings["gemini_model"]) if key else None
        self.router = Router(local, ledger, gem, settings.get("gemini_daily_cap", 20))
        self.engine = Engine(self.world, self.router, settings, search_fn=search_fn)
        self.mode = "fake" if fake else "real"
        self.stopping = False
        self.restart_args = None          # set by main(); how to start the world again after an update
        self.update = {"current": VERSION, "available": None, "checked": None, "error": None,
                       "installing": False, "log": [], "source": updater.source()["label"]}
        self.update_lock = threading.Lock()

    # ------------------------------------------------------------- updates
    def check_updates(self):
        with self.update_lock:
            try:
                self.update["available"] = updater.check()
                self.update["error"] = None
            except updater.UpdateError as e:
                self.update["error"] = str(e)
            self.update["checked"] = time.strftime("%Y-%m-%d %H:%M")
        return self.update

    def update_loop(self):
        time.sleep(20)
        while not self.stopping:
            self.check_updates()
            for _ in range(6 * 3600):        # every 6 hours
                if self.stopping:
                    return
                time.sleep(1)

    def install_update(self):
        """Runs in a thread: pause, install, save, restart. On failure the world keeps running."""
        avail = self.update.get("available")
        if not avail or self.update["installing"]:
            return
        self.update["installing"] = True
        self.update["log"] = []
        say = lambda m: self.update["log"].append(m)  # noqa: E731
        with self.world.lock:
            was_paused = self.world.state["paused"]
            self.world.state["paused"] = True
        try:
            updater.install(avail["version"], say=say)
        except updater.UpdateError as e:
            self.update["error"] = str(e)
            self.update["installing"] = False
            with self.world.lock:
                self.world.state["paused"] = was_paused
            say(f"Update failed: {e}")
            return
        with self.world.lock:
            self.world.state["paused"] = was_paused
            self.world.add_event(None, "world", f"Olympus World was updated to {avail['version']}.")
        say("Restarting the world...")
        self.shutdown()
        self.restart()

    def restart(self):
        """Start the updated world in this same window, then let this old one go."""
        args = [sys.executable, "-m", "olympus_world.server", "--after-update", "--no-browser"] + (self.restart_args or [])
        kw = {"cwd": updater.ROOT}
        if os.name != "nt":
            kw["start_new_session"] = True
        subprocess.Popen(args, **kw)    # inherits this console window, so it stays in the taskbar
        time.sleep(0.5)
        os._exit(0)

    def physics_loop(self):
        last = time.time()
        last_save = last
        while not self.stopping:
            time.sleep(0.25)
            now = time.time()
            self.world.step(min(1.0, now - last))
            last = now
            if now - last_save > 10:
                self.world.save()
                last_save = now

    def start_threads(self):
        for target in (self.physics_loop, self.engine.loop, self.update_loop):
            t = threading.Thread(target=target, daemon=True)
            t.start()

    def shutdown(self):
        self.stopping = True
        self.engine.stop = True
        self.world.save()

    # ------------------------------------------------------------- api data
    def status(self):
        usage = self.router.ledger.snapshot()
        current = self.engine.current
        name = self.world.state["agents"][current]["name"] if current else None
        return {
            "version": VERSION, "mode": self.mode,
            "local_model": self.settings["local_model"] if self.mode == "real" else "fake",
            "gemini": self.router.gemini is not None,
            "gemini_used": usage.get("gemini", 0), "gemini_cap": self.router.gemini_cap,
            "web_used": usage.get("web", 0), "web_cap": self.engine.web_cap,
            "local_used": usage.get("local", 0),
            "thinking": name, "last_error": self.router.last_error or self.router.gemini_error,
            "last_brain": self.router.last_brain,
            "update": {k: v for k, v in self.update.items()},
        }

    def journal(self, kind, agent=None, limit=150):
        key = {"diaries": "diaries", "searches": "searches", "talks": "talks", "events": "events"}.get(kind)
        if not key:
            return []
        with self.world.lock:
            items = list(self.world.state[key])
        if agent:
            items = [i for i in items if i.get("agent") == agent or i.get("to") == agent]
        return items[-limit:][::-1]


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            if u.path == "/api/state":
                st = app.world.public_state(q.get("rev", [None])[0])
                st["status"] = app.status()
                return self._json(st)
            if u.path == "/api/journal":
                kind = q.get("kind", ["events"])[0]
                agent = q.get("agent", [None])[0] or None
                return self._json(app.journal(kind, agent))
            return self._static(u.path)

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            if u.path == "/api/shutdown":
                # used by the installer before an update. The custom header can't be sent by
                # other websites (browsers would need a CORS preflight we never allow).
                if self.headers.get("X-Olympus-Installer") != "1":
                    return self._json({"error": "forbidden"}, 403)
                self._json({"stopping": True})
                def stop():
                    app.shutdown()
                    os._exit(0)
                threading.Timer(0.3, stop).start()
                return None
            # actions from the viewer carry a custom header, which other websites can't send
            from_viewer = self.headers.get("X-Olympus") == "1"
            if u.path == "/api/update/check":
                if not from_viewer:
                    return self._json({"error": "forbidden"}, 403)
                return self._json(app.check_updates())
            if u.path == "/api/update/install":
                if not from_viewer:
                    return self._json({"error": "forbidden"}, 403)
                if not app.update.get("available"):
                    return self._json({"error": "no update available"}, 409)
                threading.Thread(target=app.install_update, daemon=True).start()
                return self._json({"installing": True})
            if u.path == "/api/shader_result":
                # the viewer test-compiled (or timed) a god's shader and reports how it went
                if not from_viewer:
                    return self._json({"error": "forbidden"}, 403)
                try:
                    n = min(int(self.headers.get("Content-Length") or 0), 4000)
                    body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                except (ValueError, UnicodeDecodeError):
                    return self._json({"error": "bad request"}, 400)
                ok = app.world.shader_result(str(body.get("target", "")), str(body.get("hash", "")),
                                             bool(body.get("ok")), str(body.get("error", ""))[:300])
                return self._json({"recorded": ok})
            if u.path == "/api/requests/answer":
                # you answered a god's request in the Requests tab
                if not from_viewer:
                    return self._json({"error": "forbidden"}, 403)
                try:
                    n = min(int(self.headers.get("Content-Length") or 0), 4000)
                    body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                except (ValueError, UnicodeDecodeError):
                    return self._json({"error": "bad request"}, 400)
                r = app.world.answer_request(str(body.get("id", "")), str(body.get("status", "")), str(body.get("note", ""))[:400])
                if r is None:
                    return self._json({"error": "no such request"}, 404)
                return self._json({"request": {k: v for k, v in r.items() if k != "game_minutes"}})
            if u.path in ("/api/pause", "/api/resume"):
                if not from_viewer:
                    return self._json({"error": "forbidden"}, 403)
                with app.world.lock:
                    app.world.state["paused"] = u.path.endswith("pause")
                    app.world.add_event(None, "world", "You paused the world." if app.world.state["paused"]
                                        else "You let the world run again.")
                return self._json({"paused": app.world.state["paused"]})
            return self._json({"error": "not found"}, 404)

        def _static(self, path):
            if path in ("", "/"):
                path = "/index.html"
            full = os.path.normpath(os.path.join(WEB_DIR, path.lstrip("/")))
            if not full.startswith(os.path.normpath(WEB_DIR)) or not os.path.isfile(full):
                return self._json({"error": "not found"}, 404)
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            with open(full, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def already_running(port):
    """If an Olympus World is already on this port, return its mode."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
            st = json.loads(r.read()).get("status", {})
            if st.get("version"):
                return st.get("mode", "real")
    except Exception:
        pass
    return None


def _wait_for_enter():
    try:
        if sys.stdin and sys.stdin.isatty():
            input("Press Enter to close this window.")
    except Exception:
        time.sleep(15)


def _save_on_window_close(app):
    """Windows sends CTRL_CLOSE as SIGBREAK when the window's X is clicked: save first."""
    import signal
    if hasattr(signal, "SIGBREAK"):
        def handler(*_):
            try:
                app.shutdown()
            finally:
                os._exit(0)
        signal.signal(signal.SIGBREAK, handler)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run Olympus World")
    ap.add_argument("--fake", action="store_true", help="no AI: gods act randomly (for testing)")
    ap.add_argument("--data", default=None, help="data folder (default: data)")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--after-update", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    settings = load_settings()
    port = args.port or (int(settings["port"]) + (1 if args.fake else 0))
    url = f"http://127.0.0.1:{port}/"
    running = None if args.after_update else already_running(port)
    if running:
        print(f"Olympus World is already running ({running} mode). Opening the viewer...")
        if not args.no_browser:
            webbrowser.open(url)
        time.sleep(2)
        return 0
    data_dir = args.data or (os.path.join(DEFAULT_DATA_DIR, "fake") if args.fake else DEFAULT_DATA_DIR)
    app = App(data_dir, settings, fake=args.fake)
    server = None
    for attempt in range(40 if args.after_update else 1):   # after an update, wait for the old world to let go
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
            break
        except OSError as e:
            err = e
            time.sleep(0.5)
    if server is None:
        e = err
        print(f"Couldn't start: port {port} is being used by another program ({e}).")
        print('Fix: open config\\settings.json in Notepad, change "port" to another number (like 8799), save, try again.')
        _wait_for_enter()
        return 1
    app.restart_args = (["--fake"] if args.fake else []) + (["--data", args.data] if args.data else []) \
        + (["--port", str(args.port)] if args.port else [])
    _save_on_window_close(app)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(
                "Olympus World - running (close this window to stop)" + (" - TEST MODE" if args.fake else ""))
        except Exception:
            pass
    app.start_threads()
    print(f"Olympus World {VERSION} is running ({app.mode} mode).")
    print(f"  Local model : {settings['local_model'] if not args.fake else 'none (fake)'}")
    print(f"  Gemini      : {'on, max ' + str(app.router.gemini_cap) + '/day' if app.router.gemini else 'off'}")
    print(f"  Viewer      : {url}")
    print("  Leave this window open. Close it (or press Ctrl+C) to stop the world; it saves automatically.")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()
        server.server_close()
        print("World saved. Goodbye.")


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        import traceback
        traceback.print_exc()
        print("\nSomething went wrong. Copy the text above and send it to Claude.")
        _wait_for_enter()
        code = 1
    sys.exit(code)
