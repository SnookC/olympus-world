"""Olympus World updates, the same way Goldmire does it.

The world checks your GitHub now and then for a newer version. When there is
one, an "Update" button appears in the viewer. Pressing it:
  1. downloads the new version,
  2. checks it before touching anything (right program, right version, all code compiles),
  3. backs up every file it is about to replace or remove (in the "backups" folder),
  4. swaps the files in, putting the old ones back if anything goes wrong,
  5. restarts the world (the gods pick up exactly where they were).

Never touched by an update: the gods' world and memories (data/), your Gemini key
(config/secrets.env) and your settings (config/settings.json).

Where updates come from is set in update.json: {"repo": "name/olympus-world", "branch": "main"}.
An empty "repo" switches updates off.
"""
import io
import json
import os
import py_compile
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(ROOT, "version.json")
SOURCE_FILE = os.path.join(ROOT, "update.json")
BACKUP_DIR = os.path.join(ROOT, "backups")
KEEP_BACKUPS = 3
TIMEOUT = 30
MAX_ZIP = 60 * 1024 * 1024
UA = "OlympusWorld-updater"

# Yours. An update never replaces or removes these.
PROTECTED_DIRS = {"data", "backups", ".git", "__pycache__", "installer", ".github"}
PROTECTED_FILES = {"config/secrets.env", "config/settings.json", "python_path.txt",
                   "Uninstall Olympus World.exe", "olympus.ico"}
# Folders that belong to the program: files in them that the new version no longer has get removed.
PROGRAM_DIRS = ("olympus_world", "web", "tools", "tests")
# An update must contain these, or it isn't Olympus World.
REQUIRED = ("version.json", "olympus_world/server.py", "olympus_world/world.py", "web/index.html", "web/app.js")

# Tests can point the updater at a pretend GitHub.
RAW_BASE = os.environ.get("OLYMPUS_UPDATE_RAW", "https://raw.githubusercontent.com")
ZIP_BASE = os.environ.get("OLYMPUS_UPDATE_ZIP", "https://codeload.github.com")


class UpdateError(Exception):
    pass


def _copy(src, dst):
    """Plain copy + timestamps (avoids CopyFile2, which some Windows setups lack)."""
    shutil.copyfile(src, dst)
    try:
        shutil.copystat(src, dst)
    except OSError:
        pass


def _vtuple(v):
    nums = re.findall(r"\d+", str(v))[:3]
    return tuple(int(n) for n in nums) + (0,) * (3 - len(nums))


def newer(a, b):
    """True if version a is newer than version b."""
    return _vtuple(a) > _vtuple(b)


def current_version(root=ROOT):
    try:
        with open(os.path.join(root, "version.json"), "r", encoding="utf-8") as f:
            return str(json.load(f)["version"])
    except Exception:
        return "0.0.0"


def source(root=ROOT):
    try:
        with open(os.path.join(root, "update.json"), "r", encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        s = {}
    repo = str(s.get("repo") or "").strip().strip("/")
    branch = str(s.get("branch") or "main").strip()
    if repo and not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        repo = ""
    if not re.fullmatch(r"[\w./-]+", branch):
        branch = "main"
    return {"repo": repo, "branch": branch, "label": f"github.com/{repo}" if repo else "off"}


def _get(url, limit):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = r.read(limit + 1)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("the update source wasn't found on GitHub (is the repository created and public?)")
        raise UpdateError(f"GitHub answered HTTP {e.code}")
    except urllib.error.URLError as e:
        raise UpdateError(f"couldn't reach GitHub ({e.reason})")
    except (TimeoutError, OSError) as e:
        raise UpdateError(f"couldn't reach GitHub ({e})")
    if len(data) > limit:
        raise UpdateError("the download was unexpectedly large")
    return data


def check(root=ROOT):
    """Returns {"version", "notes"} if a newer version is published, else None."""
    src = source(root)
    if not src["repo"]:
        return None
    url = f"{RAW_BASE}/{src['repo']}/{src['branch']}/version.json?t={int(time.time())}"
    try:
        info = json.loads(_get(url, 100_000).decode("utf-8"))
    except ValueError:
        raise UpdateError("the published version file isn't readable")
    if not isinstance(info, dict):
        raise UpdateError("the published version file isn't readable")
    v = str(info.get("version", ""))
    if not v:
        raise UpdateError("the published version file has no version")
    if newer(v, current_version(root)):
        return {"version": v, "notes": str(info.get("notes", ""))[:500]}
    return None


def _rel_ok(rel):
    parts = rel.split("/")
    return rel and not rel.startswith("/") and ".." not in parts and ":" not in rel and "\\" not in rel


def _protected(rel):
    first = rel.split("/")[0]
    return first in PROTECTED_DIRS or rel in PROTECTED_FILES


def _extract(zip_bytes, dest):
    """Unpack GitHub's zip (one top folder) into dest. Returns the list of relative file paths."""
    try:
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise UpdateError("the download wasn't a valid zip")
    names = [n for n in z.namelist() if not n.endswith("/")]
    if not names:
        raise UpdateError("the download was empty")
    top = names[0].split("/")[0] + "/"
    files = []
    for n in names:
        if not n.startswith(top):
            raise UpdateError("the download had an unexpected layout")
        rel = n[len(top):]
        if not rel:
            continue
        if not _rel_ok(rel):
            raise UpdateError(f"the download contained an unsafe path ({rel})")
        out = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with z.open(n) as src, open(out, "wb") as f:
            shutil.copyfileobj(src, f)
        files.append(rel)
    return files


def _verify(stage, files, expected_version):
    for req in REQUIRED:
        if req not in files:
            raise UpdateError(f"the download is missing {req}; it doesn't look like Olympus World")
    got = current_version(stage)
    if got != expected_version:
        raise UpdateError(f"the download is version {got}, expected {expected_version}")
    for rel in files:
        if rel.endswith(".py"):
            try:
                py_compile.compile(os.path.join(stage, *rel.split("/")), doraise=True,
                                   cfile=os.path.join(stage, "__pyc_check__", rel.replace("/", "_") + "c"))
            except py_compile.PyCompileError as e:
                raise UpdateError(f"{rel} in the update has an error: {e.msg.strip()[:200]}")
    shutil.rmtree(os.path.join(stage, "__pyc_check__"), ignore_errors=True)


def _program_files(root):
    out = []
    for d in PROGRAM_DIRS:
        base = os.path.join(root, d)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x != "__pycache__"]
            for fn in filenames:
                rel = os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/")
                out.append(rel)
    return out


def _prune_backups():
    if not os.path.isdir(BACKUP_DIR):
        return
    olds = sorted(d for d in os.listdir(BACKUP_DIR) if os.path.isdir(os.path.join(BACKUP_DIR, d)))
    for d in olds[:-KEEP_BACKUPS]:
        shutil.rmtree(os.path.join(BACKUP_DIR, d), ignore_errors=True)


def install(expected_version, say=print, root=ROOT):
    """Download, verify, back up, swap. Raises UpdateError (and rolls back) on any problem."""
    src = source(root)
    if not src["repo"]:
        raise UpdateError("updates are switched off (no repo in update.json)")
    say(f"Downloading Olympus World {expected_version} from {src['label']}...")
    data = _get(f"{ZIP_BASE}/{src['repo']}/zip/refs/heads/{src['branch']}", MAX_ZIP)
    stage = tempfile.mkdtemp(prefix="olympus_update_")
    try:
        files = [f for f in _extract(data, stage) if not _protected(f)]
        say("Checking the new version...")
        _verify(stage, files, expected_version)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = os.path.join(BACKUP_DIR if root == ROOT else os.path.join(root, "backups"),
                              f"{stamp}-before-{expected_version}")
        new_set = set(files)
        removed = [f for f in _program_files(root) if f not in new_set and not _protected(f)]
        touched = [f for f in files if os.path.exists(os.path.join(root, *f.split("/")))] + removed
        say(f"Backing up {len(touched)} files...")
        for rel in touched:
            dst = os.path.join(backup, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            _copy(os.path.join(root, *rel.split("/")), dst)
        created = []
        try:
            say(f"Installing {len(files)} files...")
            for rel in files:
                target = os.path.join(root, *rel.split("/"))
                if not os.path.exists(target):
                    created.append(target)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                tmp = target + ".updating"
                _copy(os.path.join(stage, *rel.split("/")), tmp)
                os.replace(tmp, target)
            for rel in removed:
                os.remove(os.path.join(root, *rel.split("/")))
        except Exception as e:
            say("Something went wrong; putting the old files back...")
            for rel in touched:
                b = os.path.join(backup, *rel.split("/"))
                if os.path.exists(b):
                    os.makedirs(os.path.dirname(os.path.join(root, *rel.split("/"))), exist_ok=True)
                    _copy(b, os.path.join(root, *rel.split("/")))
            for c in created:
                try:
                    os.remove(c)
                except OSError:
                    pass
            raise UpdateError(f"installing failed ({e}); your previous version was restored")
        for d in PROGRAM_DIRS:
            shutil.rmtree(os.path.join(root, d, "__pycache__"), ignore_errors=True)
        if root == ROOT:
            _prune_backups()
        say(f"Installed Olympus World {expected_version}.")
        return expected_version
    finally:
        shutil.rmtree(stage, ignore_errors=True)
