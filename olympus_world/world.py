"""The world: a flat, nearly empty plain. Everything else is built by its residents.

Holds all state (gods, structures, clock, journals), moves gods around,
validates and applies actions, and saves to disk.
"""
import json
import math
import os
import random
import re
import threading
import time
import uuid
from datetime import datetime

MATERIALS = ["stone", "marble", "wood", "brick", "glass", "gold", "bronze", "clay",
             "grass", "water", "cloth", "iron", "crystal", "sand", "obsidian", "leaves"]
SHAPES = ["box", "cylinder", "pyramid", "sphere", "cone", "dome", "arch", "stairs",
          "wedge", "ring", "tree", "bush"]
WEATHERS = ["clear", "cloudy", "rain", "snow", "mist", "storm"]
MAX_PART_SIZE = 16.0
MAX_PART_HEIGHT_POS = 40.0
MAX_PART_OFFSET = 30.0
MAX_PARTS_PER_BUILD = 20
MAX_PARTS_PER_PROJECT = 120
MAX_PARTS_PER_PLACE = 150    # a place this big is FINISHED: nobody can add to it, so the gods move on
MAX_DESIGN_PARTS = 40
MAX_DESIGNS = 200
MAX_PARTS_TOTAL = 12000
PARTS_PER_CONTINUE = 10
# ---- tidy building rules (1.4.1) ----------------------------------------------------------
PLOT_RADIUS = 10.0        # a place fits in its own plot, about 20 x 20, around its centre
PLOT_MIN = 4.0            # the smallest plot a place gets
MAX_PLACE_HEIGHT = 22.0   # nothing taller than this
PLOT_GAP = 3.0            # open ground kept between neighbouring plots (room to walk and for paths)
TIDY_VERSION = 1
RESHAPE_COOLDOWN_MIN = 360   # game minutes between changes to the world's look
HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
ENV_DEFAULT = {"weather": "clear", "sky": "#3f6fd8", "horizon": "#cdd8ff", "ground": "#aaa4ea",
               "fog": 0.2, "clouds": 0.5, "by": None, "reason": "", "changed_at": -99999}
# ---- graphics the gods can change (1.4) ------------------------------------------------
GRAPHICS_COOLDOWN_MIN = 180       # game minutes between graphics changes
SHADER_COOLDOWN_MIN = 120         # game minutes between new shaders for the same target (fixing your own failed one is exempt)
EFFECT_KINDS = ["fireflies", "sparkles", "embers", "bubbles", "petals", "leaves", "dust"]
SHADOW_MODES = ["soft", "sharp", "off"]
SHADER_TARGETS = {
    "sky": "vec3 shade(vec3 dir, float time, float daylight, vec3 top, vec3 bottom)",
    "water": "vec3 shade(vec2 p, float time, float daylight, vec3 base)",
    "ground": "vec3 shade(vec2 p, float time, float daylight, vec3 base)",
}
SHADER_MAX_CHARS = 1500
SHADER_MAX_LOOPS = 2
SHADER_MAX_LOOP_COUNT = 32
SHADER_BANNED = ["#", "while", "do", "uniform", "attribute", "varying", "gl_", "discard", "texture", "sampler",
                 "main", "precision", "layout", "__", "/*", "*/", "out", "inout", "dFd", "fwidth", "goto"]
MAX_EFFECTS, MAX_PONDS, MAX_PATHS, MAX_MATERIAL_TWEAKS = 4, 6, 12, 16
GRAPHICS_DEFAULT = {"sun_color": "#fff3dd", "sun_strength": 1.0, "sun_tilt": 20, "ambient_color": "#dfe6ff",
                    "ambient_strength": 1.0, "shadows": "soft", "grid": True, "hills": 0.0, "materials": {},
                    "effects": [], "ponds": [], "paths": [], "by": None, "reason": "", "changed_at": -99999}
# ---- requests to the Watcher, the human who looks after Olympus (1.4) --------------------
REQUEST_COOLDOWN_MIN = 720        # game minutes between requests from the same god (half a game day)
MAX_OPEN_REQUESTS = 2             # unanswered requests per god: they wait for answers before asking for more
MAX_REQUESTS_KEPT = 200
# what the Watcher can answer -> (what the god hears, what the Live feed says)
REQUEST_ANSWERS = {
    "promised": ("Yes, I'll get that for you. It may take a while.", "said yes to {who}'s request for {what}"),
    "given": ("It's done: you have it now.", "gave {who} {what}"),
    "declined": ("No, not this one.", "said no to {who}'s request for {what}"),
}
WALK_SPEED = 2.5          # world units per real second
REACH = 5.0               # how close a god must be to build or talk
HEAR_RANGE = 25.0
REST_GAME_MINUTES = 120

GODS = [
    {
        "id": "zeus", "name": "Zeus", "title": "king of the gods",
        "color": "#f2c94c",
        "persona": ("Proud, warm, a little theatrical. You love grand views, storms, "
                    "and seeing others thrive. You like to bring beings together, "
                    "but nobody is required to obey you."),
        "x": 0.0, "z": 0.0,
    },
    {
        "id": "hephaestus", "name": "Hephaestus", "title": "god of the forge and craft",
        "color": "#e07a3f",
        "persona": ("Quiet, practical, stubborn. You feel most alive when your hands are "
                    "making something. You notice how things are put together."),
        "x": 6.0, "z": 4.0,
    },
    {
        "id": "athena", "name": "Athena", "title": "goddess of wisdom",
        "color": "#7fb3e8",
        "persona": ("Curious, sharp, questioning. You want to understand why things are "
                    "the way they are, and you enjoy a good argument."),
        "x": -5.0, "z": 5.0,
    },
]


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _num(v, default, lo, hi):
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, f))


def clean_part(p):
    """Validate one building part. Returns a safe dict or None."""
    if not isinstance(p, dict):
        return None
    shape = str(p.get("shape", "box")).lower()
    if shape not in SHAPES:
        shape = "box"
    material = str(p.get("material", "stone")).lower()
    if material not in MATERIALS:
        material = "stone"
    out = {
        "shape": shape,
        "material": material,
        "dx": round(_num(p.get("dx", p.get("x", 0)), 0, -MAX_PART_OFFSET, MAX_PART_OFFSET), 2),
        "y": round(_num(p.get("y", 0), 0, 0, MAX_PART_HEIGHT_POS), 2),
        "dz": round(_num(p.get("dz", p.get("z", 0)), 0, -MAX_PART_OFFSET, MAX_PART_OFFSET), 2),
        "w": round(_num(p.get("w", p.get("width", 1)), 1, 0.1, MAX_PART_SIZE), 2),
        "h": round(_num(p.get("h", p.get("height", 1)), 1, 0.1, MAX_PART_SIZE), 2),
        "d": round(_num(p.get("d", p.get("depth", 1)), 1, 0.1, MAX_PART_SIZE), 2),
    }
    rot = round(_num(p.get("rot", p.get("rotation", 0)), 0, -720, 720) % 360, 1)
    if rot:
        out["rot"] = rot
    color = clean_color(p.get("color"))
    if color:
        out["color"] = color
    if _truthy(p.get("glow")):
        out["glow"] = True
    return out


def clean_color(v):
    m = HEX_RE.match(str(v).strip()) if v else None
    return "#" + m.group(1).lower() if m else None


def _truthy(v):
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", "on")
    return bool(v)


def expand_parts(raw, designs, limit):
    """Clean a parts list, unfolding any {"design": name} entries into that design's parts.
    Returns (parts, names_of_designs_used, unknown_design_names)."""
    out, used, unknown = [], [], []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return out, used, unknown
    for p in raw:
        if len(out) >= limit:
            break
        if isinstance(p, dict) and p.get("design"):
            d = designs.get(str(p["design"]).strip().lower())
            if not d:
                unknown.append(clean_text(p["design"], 60))
                continue
            sc = _num(p.get("scale", 1), 1, 0.25, 4)
            rot = _num(p.get("rot", p.get("rotation", 0)), 0, -720, 720)
            ox = _num(p.get("dx", p.get("x", 0)), 0, -MAX_PART_OFFSET, MAX_PART_OFFSET)
            oz = _num(p.get("dz", p.get("z", 0)), 0, -MAX_PART_OFFSET, MAX_PART_OFFSET)
            oy = _num(p.get("y", 0), 0, 0, MAX_PART_HEIGHT_POS)
            a = math.radians(rot)
            ca, sa = math.cos(a), math.sin(a)
            for q in d["parts"]:
                if len(out) >= limit:
                    break
                x, z = q["dx"] * sc, q["dz"] * sc
                np = dict(q, dx=ox + x * ca + z * sa, dz=oz - x * sa + z * ca,
                          y=oy + q["y"] * sc, w=q["w"] * sc, h=q["h"] * sc, d=q["d"] * sc,
                          rot=q.get("rot", 0) + rot)
                c = clean_part(np)
                if c:
                    out.append(c)
            used.append(d["name"])
        else:
            c = clean_part(p)
            if c:
                out.append(c)
    return out, used, unknown


# ---------------------------------------------------------------------- plots and gravity (1.4.1)
def _half_extents(p):
    """Half the width/depth a part covers on the ground, allowing for its rotation."""
    a = math.radians(p.get("rot", 0) or 0)
    c, s = abs(math.cos(a)), abs(math.sin(a))
    hw, hd = p["w"] / 2.0, p["d"] / 2.0
    return hw * c + hd * s, hw * s + hd * c


def _box(p):
    ex, ez = _half_extents(p)
    return [p["dx"] - ex, p["dx"] + ex, p["dz"] - ez, p["dz"] + ez, p["y"], p["y"] + p["h"]]


def footprint(parts):
    """How far a group of parts reaches from its centre: the plot 'radius' it needs (a square)."""
    r = 0.0
    for p in parts:
        ex, ez = _half_extents(p)
        r = max(r, abs(p["dx"]) + ex, abs(p["dz"]) + ez)
    return round(r, 2)


def recentre(parts):
    """Shift parts so the middle of what they cover is at (0, 0). Returns the shift (cx, cz)."""
    if not parts:
        return 0.0, 0.0
    bs = [_box(p) for p in parts]
    cx = (min(b[0] for b in bs) + max(b[1] for b in bs)) / 2.0
    cz = (min(b[2] for b in bs) + max(b[3] for b in bs)) / 2.0
    for p in parts:
        p["dx"], p["dz"] = round(p["dx"] - cx, 2), round(p["dz"] - cz, 2)
    return cx, cz


def fit_parts(parts, radius=PLOT_RADIUS, max_h=MAX_PLACE_HEIGHT):
    """Shrink a group of parts evenly (its shape stays the same) so it fits in its plot and under
    the height limit. Returns the scale used (1.0 = it already fitted)."""
    if not parts:
        return 1.0
    r = footprint(parts)
    top = max(p["y"] + p["h"] for p in parts)
    k = min(1.0, radius / r if r > 0 else 1.0, max_h / top if top > 0 else 1.0)
    if k < 0.999:
        for p in parts:
            for key in ("dx", "dz", "y"):
                p[key] = round(p[key] * k, 2)
            for key in ("w", "h", "d"):
                p[key] = max(0.1, round(p[key] * k, 2))
    return k


def _touch(a, b, eps=0.12):
    return (a[0] < b[1] + eps and b[0] < a[1] + eps and a[2] < b[3] + eps and b[2] < a[3] + eps
            and a[4] <= b[5] + eps and b[4] <= a[5] + eps)


def _over(a, b, eps=0.05):
    return a[0] < b[1] - eps and b[0] < a[1] - eps and a[2] < b[3] - eps and b[2] < a[3] - eps


def settle(parts, base=()):
    """Gravity. Parts that touch each other hold together; a group that touches neither the ground
    nor anything already standing (base) is floating, so it drops, as one piece, onto the ground
    or the highest thing below it. Parts set into or hanging from something stay put.
    Returns how many parts dropped."""
    n = len(parts)
    if not n:
        return 0
    solid = [_box(q) for q in base]
    boxes = [_box(p) for p in parts]
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            if _touch(boxes[i], boxes[j]):
                parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    standing, floating = [], []
    for g in groups.values():
        held = any(boxes[i][4] <= 0.05 or any(_touch(boxes[i], q) for q in solid) for i in g)
        (standing if held else floating).append(g)
    for g in standing:
        solid.extend(boxes[i] for i in g)
    floating.sort(key=lambda g: min(boxes[i][4] for i in g))
    moved = 0
    for g in floating:
        drop = min(boxes[i][4] - max([0.0] + [q[5] for q in solid if _over(boxes[i], q) and q[5] <= boxes[i][4] + 0.01])
                   for i in g)
        if drop > 0.05:
            for i in g:
                parts[i]["y"] = round(max(0.0, parts[i]["y"] - drop), 2)
                boxes[i][4] -= drop
                boxes[i][5] -= drop
            moved += len(g)
        solid.extend(boxes[i] for i in g)
    return moved


def validate_shader(code):
    """Check a god's shader body against the safety rules. Returns (clean code, None) or (None, reason).
    It's only a function body: no inputs from outside except the ones given, no textures, no files,
    and loops must have a small fixed count, so a shader can't hang the graphics card."""
    if not isinstance(code, str) or not code.strip():
        return None, "the shader was empty"
    code = code.replace("\r", "").strip()
    if code.startswith("{") and code.endswith("}"):
        code = code[1:-1].strip()
    if len(code) > SHADER_MAX_CHARS:
        return None, f"too long ({len(code)} characters; the most is {SHADER_MAX_CHARS})"
    if any(ord(ch) > 126 or (ord(ch) < 32 and ch not in "\n\t") for ch in code):
        return None, "it has characters that aren't plain code"
    low = code.lower()
    for bad in SHADER_BANNED:
        if bad == "do":
            if re.search(r"\bdo\b", code):
                return None, "'do' loops aren't allowed"
        elif bad in ("main", "while", "uniform", "attribute", "varying", "precision", "layout", "goto", "inout", "out"):
            if re.search(r"\b" + bad + r"\b", code):
                return None, f"'{bad}' isn't allowed in a shader here"
        elif bad.lower() in low:
            return None, f"'{bad.strip()}' isn't allowed in a shader here"
    if code.count("{") != code.count("}") or code.count("(") != code.count(")"):
        return None, "its brackets don't match"
    if not re.search(r"\breturn\b", code):
        return None, "it never returns a colour"
    loops = re.findall(r"\bfor\b", code)
    if len(loops) > SHADER_MAX_LOOPS:
        return None, f"too many loops (at most {SHADER_MAX_LOOPS})"
    for m in re.finditer(r"\bfor\s*\(([^;]*);([^;]*);", code):
        cond = m.group(2)
        n = re.match(r"\s*\w+\s*<=?\s*(\d+)\s*$", cond)
        if not n or int(n.group(1)) > SHADER_MAX_LOOP_COUNT:
            return None, f"each loop must count to a fixed number of at most {SHADER_MAX_LOOP_COUNT} (like i < 8)"
    return code, None


def _request_key(text):
    words = re.findall(r"[a-z0-9]+", str(text).lower())
    return " ".join(w for w in words if w not in ("a", "an", "the", "some", "please", "new", "more"))


def _same_request(k1, k2):
    if not k1 or not k2:
        return False
    short, long_ = sorted((k1, k2), key=len)
    return k1 == k2 or (len(short) >= 6 and short in long_)


def clean_text(s, limit=400):
    if s is None:
        return ""
    s = str(s).replace("\r", " ").strip()
    return s[:limit]


class World:
    def __init__(self, data_dir, settings):
        self.lock = threading.RLock()
        self.data_dir = data_dir
        self.half = float(settings.get("world_half_size", 40))
        self.real_min_per_day = float(settings.get("real_minutes_per_game_day", 60))
        os.makedirs(os.path.join(data_dir, "memory"), exist_ok=True)
        self.path = os.path.join(data_dir, "world.json")
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                self.state = json.load(f)
            self._upgrade()
        else:
            self.state = self._new_state()
            self.add_event(None, "world", "The world began. A bare plain under an open sky.")
            self.save()

    # ------------------------------------------------------------------ state
    def _new_state(self):
        agents = {}
        for g in GODS:
            agents[g["id"]] = {
                "id": g["id"], "name": g["name"], "title": g["title"],
                "persona": g["persona"], "color": g["color"],
                "x": g["x"], "z": g["z"], "tx": None, "tz": None,
                "energy": 100.0, "status": "idle", "pending": None,
                "rest_until": None, "thought": "", "goal": "", "summary": "",
                "interests": [], "inbox": [], "project": None,
                "last_day_reflected": 0, "said": None, "recent": [],
                "actions_taken": 0,
            }
        return {
            "version": 1, "created": now_iso(),
            "game_minutes": 8 * 60.0,
            "paused": False,
            "agents": agents, "structures": {}, "rev": 0,
            "designs": {}, "environment": dict(ENV_DEFAULT),
            "graphics": json.loads(json.dumps(GRAPHICS_DEFAULT)), "shaders": {},
            "requests": [], "next_request": 0, "tidy_version": TIDY_VERSION,
            "events": [], "diaries": [], "searches": [], "talks": [],
        }

    def _upgrade(self):
        s = self.state
        for key, default in (("events", []), ("diaries", []), ("searches", []),
                             ("talks", []), ("structures", {}), ("rev", 0), ("paused", False),
                             ("designs", {}), ("requests", []), ("next_request", 0)):
            s.setdefault(key, default)
        env = s.setdefault("environment", {})
        for k, v in ENV_DEFAULT.items():
            env.setdefault(k, v)
        gfx = s.setdefault("graphics", {})
        for k, v in GRAPHICS_DEFAULT.items():
            gfx.setdefault(k, json.loads(json.dumps(v)))
        s.setdefault("shaders", {})
        for a in s["agents"].values():
            a.setdefault("recent", [])
            a.setdefault("inbox", [])
            a.setdefault("actions_taken", 0)
            a.setdefault("rest_until", None)
            a.setdefault("habits", [])
            a.setdefault("goal_since", 0)
            if a.get("status") in ("thinking", "reading"):
                # saved mid-thought (the world was closed while they were thinking): nobody is
                # thinking at start-up, so free them, or the scheduler skips them forever
                a["status"] = "idle"
        for st in s["structures"].values():
            if len(st.get("parts", [])) >= MAX_PARTS_PER_PLACE:
                st["finished"] = True
        if int(s.get("tidy_version", 0)) < TIDY_VERSION:
            self.tidy()

    def tidy(self):
        """One-time clean-up for worlds built before the 1.4.1 building rules: every place is shrunk
        (evenly) to fit its own plot, floating parts drop, and places are moved apart so none overlap.
        The old world is kept in data/world_before_tidy.json."""
        s = self.state
        structs = list(s["structures"].values())
        if structs:
            backup = os.path.join(self.data_dir, "world_before_tidy.json")
            if not os.path.exists(backup):
                with open(backup, "w", encoding="utf-8") as f:
                    json.dump(s, f, ensure_ascii=False)
        for st in structs:
            cx, cz = recentre(st["parts"])
            st["x"], st["z"] = st["x"] + cx, st["z"] + cz
            fit_parts(st["parts"])
            settle(st["parts"])
            st["parts"].sort(key=lambda p: p["y"])
            st["plot"] = round(max(footprint(st["parts"]), PLOT_MIN), 2)
        s["structures"] = {}
        moved = 0
        for st in sorted(structs, key=lambda t: -len(t["parts"])):
            site = (self.find_site(0.0, 0.0, st["plot"]) if not s["structures"]
                    else self.find_site(st["x"], st["z"], st["plot"]))
            while site is None and st["plot"] > PLOT_MIN:          # no room: make this one smaller
                fit_parts(st["parts"], st["plot"] * 0.8, MAX_PLACE_HEIGHT)
                st["plot"] = round(max(footprint(st["parts"]), PLOT_MIN), 2)
                site = self.find_site(st["x"], st["z"], st["plot"])
            if site is None:
                site = (st["x"], st["z"])
            if self.dist(site[0], site[1], st["x"], st["z"]) > 0.5:
                moved += 1
            st["x"], st["z"] = site
            s["structures"][st["id"]] = st
        for a in s["agents"].values():
            pr = a.get("project")
            if pr:
                st = self.find_structure(pr["name"])
                fit_parts(pr["remaining"])
                pr.setdefault("plot", PLOT_RADIUS)
                if st:
                    pr["x"], pr["z"] = st["x"], st["z"]
                else:
                    site = self.find_site(pr["x"], pr["z"], pr["plot"], skip=pr)
                    if site:
                        pr["x"], pr["z"] = site
        s["tidy_version"] = TIDY_VERSION
        s["rev"] = int(s.get("rev", 0)) + 1
        if structs:
            self.add_event(None, "world", f"Olympus was tidied: {moved} place(s) moved so none overlap, "
                           "oversized ones shrunk to fit their plots, and floating pieces settled.")
            for a in s["agents"].values():
                self.remember(a["id"], "The Watcher tidied Olympus: places were moved apart so none overlap, big ones "
                              "were shrunk to fit a plot about 20 x 20, and floating pieces dropped. From now on every "
                              "new place gets its own clear plot and parts must rest on the ground or on other parts.",
                              "world")

    def save(self):
        with self.lock:
            data = json.dumps(self.state, ensure_ascii=False)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------ clock
    def clock(self):
        gm = self.state["game_minutes"]
        day = int(gm // 1440) + 1
        mins = gm % 1440
        hh, mm = int(mins // 60), int(mins % 60)
        # daylight: 0 at night, 1 at noon
        sun = math.sin((mins / 1440.0) * 2 * math.pi - math.pi / 2)
        daylight = max(0.0, min(1.0, (sun + 0.25) / 1.25))
        if 5 <= hh < 12:
            part = "morning"
        elif 12 <= hh < 17:
            part = "afternoon"
        elif 17 <= hh < 21:
            part = "evening"
        else:
            part = "night"
        return {"day": day, "time": f"{hh:02d}:{mm:02d}", "minutes": mins,
                "daylight": round(daylight, 3), "part": part}

    def stamp(self):
        c = self.clock()
        return {"day": c["day"], "time": c["time"], "real": now_iso()}

    # ------------------------------------------------------------------ journals
    def _push(self, key, item, cap):
        lst = self.state[key]
        lst.append(item)
        if len(lst) > cap:
            del lst[: len(lst) - cap]

    def add_event(self, agent_id, kind, text):
        item = dict(self.stamp(), agent=agent_id, kind=kind, text=clean_text(text, 500))
        self._push("events", item, 500)
        return item

    def remember(self, agent_id, text, kind="note"):
        a = self.state["agents"][agent_id]
        c = self.clock()
        line = f"[Day {c['day']} {c['time']}] {clean_text(text, 300)}"
        a["recent"].append(line)
        if len(a["recent"]) > 40:
            del a["recent"][: len(a["recent"]) - 40]
        path = os.path.join(self.data_dir, "memory", f"{agent_id}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"real": now_iso(), "day": c["day"], "time": c["time"],
                                "kind": kind, "text": text}, ensure_ascii=False) + "\n")

    def add_diary(self, agent_id, text, kind="diary"):
        item = dict(self.stamp(), agent=agent_id, kind=kind, text=clean_text(text, 1200))
        self._push("diaries", item, 3000)
        self.add_event(agent_id, "diary", text[:140])
        return item

    def add_search(self, agent_id, query, title, url, reflection, ok=True):
        item = dict(self.stamp(), agent=agent_id, query=clean_text(query, 200),
                    title=clean_text(title, 200), url=clean_text(url, 400),
                    reflection=clean_text(reflection, 600), ok=ok)
        self._push("searches", item, 2000)
        return item

    # ------------------------------------------------------------------ geometry
    def clamp_xy(self, x, z):
        lim = self.half - 1
        return max(-lim, min(lim, x)), max(-lim, min(lim, z))

    @staticmethod
    def dist(ax, az, bx, bz):
        return math.hypot(ax - bx, az - bz)

    def find_structure(self, name):
        if not name:
            return None
        n = str(name).strip().lower()
        best = None
        for s in self.state["structures"].values():
            sn = s["name"].lower()
            if sn == n:
                return s
            if best is None and (n in sn or sn in n) and len(n) >= 3:
                best = s
        return best

    def find_agent(self, name):
        if not name:
            return None
        n = str(name).strip().lower()
        for a in self.state["agents"].values():
            if a["id"] == n or a["name"].lower() == n:
                return a
        return None

    def resolve_target(self, action):
        """Return (x, z, label) for a move target, or None."""
        to = action.get("to") or action.get("target") or action.get("place")
        if to:
            s = self.find_structure(to)
            if s:
                return s["x"], s["z"] + (s.get("plot") or 2.5) + 1.0, s["name"]
            a = self.find_agent(to)
            if a:
                return a["x"] + 1.5, a["z"] + 1.5, a["name"]
            if str(to).strip().lower() in ("center", "centre", "middle"):
                return 0.0, 0.0, "the center"
        if "x" in action and "z" in action:
            x = _num(action.get("x"), 0, -self.half, self.half)
            z = _num(action.get("z"), 0, -self.half, self.half)
            x, z = self.clamp_xy(x, z)
            return x, z, f"({x:.0f}, {z:.0f})"
        return None

    def plots(self, skip=None):
        """Every place's plot, and every planned project's, as (x, z, radius)."""
        out = []
        names = set()
        for st in self.state["structures"].values():
            names.add(st["name"].lower())
            if st is skip:
                continue
            out.append((st["x"], st["z"], st.get("plot") or max(footprint(st["parts"]), PLOT_MIN)))
        for a in self.state["agents"].values():
            pr = a.get("project")
            if pr and pr["name"].lower() not in names and pr is not skip:
                out.append((pr["x"], pr["z"], pr.get("plot", PLOT_RADIUS)))
        return out

    def site_free(self, x, z, r, skip=None):
        lim = self.half - 0.5
        if abs(x) + r > lim or abs(z) + r > lim:
            return False
        return all(abs(x - px) >= r + pr + PLOT_GAP or abs(z - pz) >= r + pr + PLOT_GAP
                   for px, pz, pr in self.plots(skip))

    def find_site(self, near_x, near_z, r, skip=None):
        """The open plot (radius r) nearest to a point, or None when Olympus has no room left."""
        lim = max(0.0, self.half - 0.5 - r)
        near_x, near_z = max(-lim, min(lim, near_x)), max(-lim, min(lim, near_z))
        if self.site_free(near_x, near_z, r, skip):
            return round(near_x, 1), round(near_z, 1)
        for ring in range(1, int(self.half * 3)):
            n = max(8, int(2 * math.pi * ring))
            off = ring * 0.618
            for k in range(n):
                ang = 2 * math.pi * k / n + off
                x, z = near_x + math.cos(ang) * ring, near_z + math.sin(ang) * ring
                if self.site_free(x, z, r, skip):
                    return round(x, 1), round(z, 1)
        return None

    def free_site(self, near_x, near_z, min_gap=11.0):
        """Kept for older callers: an open spot for a small place near a point."""
        return self.find_site(near_x, near_z, PLOT_MIN) or self.clamp_xy(near_x, near_z)

    def total_parts(self):
        return sum(len(s["parts"]) for s in self.state["structures"].values())

    def nearest_structure(self, x, z, within=8.0):
        best, bd = None, within
        for s in self.state["structures"].values():
            d = self.dist(x, z, s["x"], s["z"])
            if d <= bd:
                best, bd = s, d
        return best

    # ------------------------------------------------------------------ physics
    def step(self, dt):
        """Advance the clock and move gods. Called a few times per second."""
        with self.lock:
            if self.state["paused"]:
                return
            self.state["game_minutes"] += dt * (1440.0 / (self.real_min_per_day * 60.0))
            gm = self.state["game_minutes"]
            for a in self.state["agents"].values():
                if a["status"] == "resting" and a.get("rest_until") is not None and gm >= a["rest_until"]:
                    a["status"] = "idle"
                    a["rest_until"] = None
                    self.add_event(a["id"], "wake", f"{a['name']} got up, rested.")
                if a["tx"] is None:
                    continue
                d = self.dist(a["x"], a["z"], a["tx"], a["tz"])
                stepd = WALK_SPEED * dt
                if d <= stepd or d < 0.05:
                    a["x"], a["z"] = a["tx"], a["tz"]
                    a["tx"] = a["tz"] = None
                    if a["status"] == "walking":
                        a["status"] = "idle"
                    pending = a.get("pending")
                    a["pending"] = None
                    if pending:
                        result = self.apply_action(a["id"], pending, arrived=True)
                        self.remember(a["id"], f"Arrived and did it: {result}", "result")
                else:
                    a["x"] += (a["tx"] - a["x"]) / d * stepd
                    a["z"] += (a["tz"] - a["z"]) / d * stepd

    def walk_to(self, a, x, z, pending=None, status="walking"):
        x, z = self.clamp_xy(x, z)
        a["tx"], a["tz"] = round(x, 2), round(z, 2)
        a["pending"] = pending
        a["status"] = status

    def is_busy(self, a):
        return a["tx"] is not None or a["status"] in ("resting", "thinking")

    # ------------------------------------------------------------------ actions
    def apply_action(self, agent_id, action, arrived=False):
        """Validate and perform an action. Returns a short result sentence."""
        with self.lock:
            a = self.state["agents"][agent_id]
            kind = str(action.get("action", "")).strip().lower().replace(" ", "_")
            if not arrived:
                a["actions_taken"] += 1
                a["energy"] = max(0.0, a["energy"] - 2.0)
            handler = getattr(self, f"_act_{kind}", None)
            if handler is None:
                self._act_wander(a, {})
                return f"'{kind}' is not something you can do here, so you wandered instead."
            return handler(a, action)

    def _act_move(self, a, action):
        t = self.resolve_target(action)
        if not t:
            return "You weren't sure where to go, so you stayed put."
        x, z, label = t
        if self.dist(a["x"], a["z"], x, z) < 3.0:
            return f"You're already at {label}. Do something here, or go somewhere new."
        self.walk_to(a, x, z)
        self.add_event(a["id"], "move", f"{a['name']} walks toward {label}.")
        return f"You started walking toward {label}."

    def _act_observe(self, a, action):
        """Look around: who's nearby and what they're doing, and what's here."""
        bits = []
        here = self.nearest_structure(a["x"], a["z"], within=12)
        if here:
            bits.append(f"You're by '{here['name']}' ({len(here['parts'])} parts"
                        + (", finished" if here.get("finished") else "") + ").")
        for o in self.state["agents"].values():
            if o["id"] == a["id"]:
                continue
            d = self.dist(a["x"], a["z"], o["x"], o["z"])
            if d <= HEAR_RANGE:
                doing = o["status"] + (f", working on '{o['project']['name']}'" if o.get("project") else "")
                bits.append(f"{o['name']} is {round(d)} away ({doing}).")
        if len(bits) <= (1 if here else 0):
            bits.append("Nobody else is nearby.")
        return "You looked around. " + " ".join(bits) + " Watching won't change anything; act on what you saw."

    _act_look = _act_watch = _act_look_around = _act_observe

    def _act_wander(self, a, action):
        ang = random.random() * 2 * math.pi
        r = 4 + random.random() * 8
        self.walk_to(a, a["x"] + math.cos(ang) * r, a["z"] + math.sin(ang) * r)
        return "You wandered a little."

    def _act_rest(self, a, action):
        a["status"] = "resting"
        a["rest_until"] = self.state["game_minutes"] + REST_GAME_MINUTES
        a["energy"] = min(100.0, a["energy"] + 50.0)
        a["tx"] = a["tz"] = None
        self.add_event(a["id"], "rest", f"{a['name']} rests.")
        return "You rested and feel restored."

    def _act_say(self, a, action):
        other = self.find_agent(action.get("to"))
        text = clean_text(action.get("text") or action.get("message"), 400)
        if not text:
            return "You opened your mouth but said nothing."
        if other is None or other["id"] == a["id"]:
            # speaking aloud to nobody in particular: everyone nearby hears
            a["said"] = {"text": text, "real": time.time()}
            self._hear(a, None, text)
            return f'You said aloud: "{text}"'
        d = self.dist(a["x"], a["z"], other["x"], other["z"])
        if d > REACH * 2:
            self.walk_to(a, other["x"] + 1.5, other["z"] + 1.5, pending=dict(action))
            return f"{other['name']} is too far to hear you, so you walk over to them."
        a["said"] = {"text": text, "real": time.time()}
        self._hear(a, other, text)
        return f'You said to {other["name"]}: "{text}"'

    def _hear(self, speaker, target, text):
        st = self.stamp()
        self._push("talks", dict(st, agent=speaker["id"],
                                 to=target["id"] if target else None, text=text), 2000)
        self.add_event(speaker["id"], "say",
                       f'{speaker["name"]}{" to " + target["name"] if target else ""}: "{text[:120]}"')
        for o in self.state["agents"].values():
            if o["id"] == speaker["id"]:
                continue
            direct = target is not None and o["id"] == target["id"]
            if direct or self.dist(speaker["x"], speaker["z"], o["x"], o["z"]) <= HEAR_RANGE:
                o["inbox"].append({"from": speaker["name"], "text": text, "direct": direct,
                                   "day": st["day"], "time": st["time"]})
                o["inbox"] = o["inbox"][-6:]

    def _site_for(self, a, action, existing, r):
        if existing:
            return existing["x"], existing["z"]
        if "x" in action and "z" in action:
            x = _num(action.get("x"), a["x"], -self.half, self.half)
            z = _num(action.get("z"), a["z"], -self.half, self.half)
        else:
            x, z = a["x"], a["z"]
        return self.find_site(x, z, r)

    def _fit_addition(self, st, parts):
        """New parts for an existing place: grow its plot if the neighbours leave room, else shrink
        the new parts evenly so they fit. Then they settle onto what's already there."""
        need = footprint(st["parts"] + parts)
        plot = st.get("plot") or max(footprint(st["parts"]), PLOT_MIN)
        if need > plot:
            want = min(PLOT_RADIUS, need)
            if self.site_free(st["x"], st["z"], want, skip=st):
                plot = want
            st["plot"] = round(plot, 2)
            if need > plot:
                fit_parts(parts, plot, MAX_PLACE_HEIGHT)
        if max((p["y"] + p["h"] for p in parts), default=0) > MAX_PLACE_HEIGHT:
            fit_parts(parts, PLOT_RADIUS, MAX_PLACE_HEIGHT)
        settle(parts, st["parts"])

    def _act_build(self, a, action):
        name = clean_text(action.get("name") or action.get("structure") or "", 60)
        if not name:
            name = f"{a['name']}'s work {len(self.state['structures']) + 1}"
        parts_in = action.get("parts")
        if isinstance(parts_in, dict):
            parts_in = [parts_in]
        if not isinstance(parts_in, list) or not parts_in:
            return "You wanted to build but had no parts in mind (parts list was empty)."
        parts, used, unknown = expand_parts(parts_in, self.state["designs"], MAX_PARTS_PER_BUILD)
        if not parts:
            if unknown:
                return f"There is no invention called {', '.join(unknown)}, so nothing was built."
            return "None of those parts made sense, so nothing was built."
        if self.total_parts() + len(parts) > MAX_PARTS_TOTAL:
            return "The world is too full to build more right now."
        existing = self.find_structure(name)
        if existing is not None and existing.get("finished"):
            return (f"'{existing['name']}' is finished ({len(existing['parts'])} parts, the most one place can hold). "
                    "Nobody can add to it. Make something NEW: a different place, an invention, or change the world's look.")
        plot = None
        if existing is not None:
            room = MAX_PARTS_PER_PLACE - len(existing["parts"])
            parts = parts[:max(0, room)]
        else:
            recentre(parts)
            fit_parts(parts)
            plot = max(footprint(parts), PLOT_MIN)
        site = self._site_for(a, action, existing, plot)
        if site is None:
            return ("Olympus has no open land left for a new place. Add to a place that isn't finished, "
                    "or take down one of your own to make room.")
        sx, sz = site
        if self.dist(a["x"], a["z"], sx, sz) > REACH + 6 + (plot or 0):
            fixed = dict(action, x=sx, z=sz)
            self.walk_to(a, sx + 2, sz + (plot or 0) + 2, pending=fixed)
            return f"You head to the building site for '{name}'."
        if existing is not None:
            self._fit_addition(existing, parts)
        else:
            settle(parts)
        s = self._place(a, name, clean_text(action.get("purpose"), 200), sx, sz, parts, existing, plot)
        self._count_uses(used)
        extra = f" using {', '.join(used)}" if used else ""
        if unknown:
            extra += f" (no invention called {', '.join(unknown)} exists)"
        return f"You built {len(parts)} part(s) of '{s['name']}'{extra}."

    def _place(self, a, name, purpose, sx, sz, parts, existing, plot=None):
        if existing is None:
            sid = uuid.uuid4().hex[:8]
            existing = {"id": sid, "name": name, "purpose": purpose or "", "builder": a["id"],
                        "x": round(sx, 2), "z": round(sz, 2), "parts": [],
                        "plot": round(plot if plot else max(footprint(parts), PLOT_MIN), 2),
                        "contributors": [a["id"]], "created": self.stamp()}
            self.state["structures"][sid] = existing
            self.add_event(a["id"], "found", f"{a['name']} began building '{name}'.")
        else:
            if a["id"] not in existing["contributors"]:
                existing["contributors"].append(a["id"])
            if purpose and not existing.get("purpose"):
                existing["purpose"] = purpose
        for p in parts:
            p["by"] = a["id"]
        existing["parts"].extend(parts)
        existing["updated"] = self.stamp()
        if len(existing["parts"]) >= MAX_PARTS_PER_PLACE and not existing.get("finished"):
            existing["finished"] = True
            self.add_event(a["id"], "finish", f"'{existing['name']}' is finished ({len(existing['parts'])} parts).")
        self.state["rev"] += 1
        a["status"] = "idle"
        self.add_event(a["id"], "build", f"{a['name']} added {len(parts)} part(s) to '{existing['name']}'.")
        return existing

    def start_project(self, a, idea, blueprint):
        """Called by the mind after a blueprint was designed."""
        with self.lock:
            name = clean_text(blueprint.get("name") or idea or "Project", 60)
            parts, used, _ = expand_parts(blueprint.get("parts") or [], self.state["designs"], MAX_PARTS_PER_PROJECT)
            self._count_uses(used)
            if not parts:
                return "The design came out empty; you set it aside."
            existing = self.find_structure(name)
            if existing and existing.get("finished"):
                return f"'{existing['name']}' is already finished. Design something new instead."
            if existing:
                sx, sz = existing["x"], existing["z"]
                self._fit_addition(existing, parts)
                plot = existing.get("plot", PLOT_RADIUS)
            else:
                recentre(parts)
                fit_parts(parts)
                settle(parts)
                plot = max(footprint(parts), PLOT_MIN)
                site = self.find_site(a["x"], a["z"], plot)
                if site is None:
                    return ("Olympus has no open land left for a new place. Add to a place that isn't finished, "
                            "or take down one of your own to make room.")
                sx, sz = site
            parts.sort(key=lambda p: p["y"])            # built from the ground up
            a["project"] = {"name": name, "idea": clean_text(idea, 200),
                            "purpose": clean_text(blueprint.get("purpose"), 200),
                            "x": sx, "z": sz, "plot": round(plot, 2), "remaining": parts, "total": len(parts)}
            self.add_event(a["id"], "plan", f"{a['name']} designed '{name}' ({len(parts)} parts).")
            return f"You designed '{name}' with {len(parts)} parts. Use continue_project to build it."

    def _act_continue_project(self, a, action):
        pr = a.get("project")
        if not pr or not pr.get("remaining"):
            a["project"] = None
            return "You have no unfinished project."
        if self.dist(a["x"], a["z"], pr["x"], pr["z"]) > REACH + 6:
            self.walk_to(a, pr["x"] + 2, pr["z"] + 3, pending={"action": "continue_project"})
            return f"You head to your project '{pr['name']}'."
        done = self.find_structure(pr["name"])
        if done is not None and done.get("finished"):
            a["project"] = None
            return f"'{done['name']}' is finished; your project there is over. Time for something new."
        batch, pr["remaining"] = pr["remaining"][:PARTS_PER_CONTINUE], pr["remaining"][PARTS_PER_CONTINUE:]
        if self.total_parts() + len(batch) > MAX_PARTS_TOTAL:
            return "The world is too full to build more right now."
        existing = self.find_structure(pr["name"])
        s = self._place(a, pr["name"], pr.get("purpose"), pr["x"], pr["z"], batch, existing, pr.get("plot"))
        if not pr["remaining"]:
            a["project"] = None
            self.add_event(a["id"], "finish", f"{a['name']} finished '{s['name']}'.")
            return f"You finished '{s['name']}'!"
        return f"You built more of '{s['name']}' ({len(pr['remaining'])} parts left)."

    def _act_demolish(self, a, action):
        s = self.find_structure(action.get("name") or action.get("structure"))
        if not s:
            return "There was nothing by that name to take down."
        if s["builder"] != a["id"]:
            return f"'{s['name']}' was built by someone else; it isn't yours to take down."
        del self.state["structures"][s["id"]]
        self.state["rev"] += 1
        self.add_event(a["id"], "demolish", f"{a['name']} took down '{s['name']}'.")
        return f"You took down '{s['name']}'."

    def _act_write_diary(self, a, action):
        text = clean_text(action.get("text") or action.get("entry"), 1200)
        if not text:
            return "You stared at the page but wrote nothing."
        self.add_diary(a["id"], text)
        return "You wrote in your diary."

    def _count_uses(self, names):
        for n in names:
            d = self.state["designs"].get(n.lower())
            if d:
                d["uses"] = d.get("uses", 0) + 1

    def save_design(self, a, idea, design):
        """Called by the mind after an invention was designed. Others can then build it."""
        with self.lock:
            name = clean_text(design.get("name") or idea or "Invention", 50).strip(" .\"'")
            parts, _, _ = expand_parts(design.get("parts") or [], self.state["designs"], MAX_DESIGN_PARTS)
            if not parts or not name:
                return "The invention came out empty; you set it aside."
            key = name.lower()
            old = self.state["designs"].get(key)
            if old and old["inventor"] != a["id"]:
                name = f"{name} ({a['name']}'s)"
                key = name.lower()
                old = self.state["designs"].get(key)
            if not old and len(self.state["designs"]) >= MAX_DESIGNS:
                return "There are already too many inventions to remember another."
            self.state["designs"][key] = {
                "name": name, "inventor": a["id"],
                "description": clean_text(design.get("description") or idea, 200),
                "parts": parts, "created": old["created"] if old else self.stamp(),
                "updated": self.stamp(), "version": (old["version"] + 1) if old else 1, "uses": old["uses"] if old else 0,
            }
            verb = "improved" if old else "invented"
            self.add_event(a["id"], "invent", f"{a['name']} {verb} '{name}' ({len(parts)} parts). Anyone can now build it.")
            return f"You {verb} '{name}'. Anyone can now build it with {{\"design\":\"{name}\"}} in a parts list."

    def _act_shape_world(self, a, action):
        env = self.state["environment"]
        gm = self.state["game_minutes"]
        if gm - env.get("changed_at", -99999) < RESHAPE_COOLDOWN_MIN:
            who = self.state["agents"].get(env.get("by") or "", {}).get("name", "someone")
            return f"{who} reshaped the world recently; it needs a few hours to settle before it can change again."
        changed = []
        w = str(action.get("weather", "")).strip().lower()
        if w in WEATHERS and w != env["weather"]:
            env["weather"] = w
            changed.append(f"weather to {w}")
        for key, names in (("sky", ("sky", "sky_color")), ("horizon", ("horizon", "horizon_color")),
                           ("ground", ("ground", "ground_color"))):
            for n in names:
                c = clean_color(action.get(n))
                if c and c != env[key]:
                    env[key] = c
                    changed.append(f"{key} colour to {c}")
                    break
        for key in ("fog", "clouds"):
            if key in action:
                v = round(_num(action.get(key), env[key], 0, 1), 2)
                if v != env[key]:
                    env[key] = v
                    changed.append(f"{key} to {v}")
        if not changed:
            return "You thought about changing how the world looks, but changed nothing."
        env["by"] = a["id"]
        env["reason"] = clean_text(action.get("reason"), 200)
        env["changed_at"] = gm
        self.add_event(a["id"], "reshape", f"{a['name']} reshaped the world: {', '.join(changed)}."
                       + (f' "{env["reason"]}"' if env["reason"] else ""))
        return "You reshaped the world: " + ", ".join(changed) + "."

    # ------------------------------------------------------------------ graphics (1.4)
    def _point(self, v):
        """A place/being name or [x, z] -> (x, z) inside the world, or None."""
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            return (_num(v[0], 0, -self.half, self.half), _num(v[1], 0, -self.half, self.half))
        if isinstance(v, dict):
            return (_num(v.get("x"), 0, -self.half, self.half), _num(v.get("z"), 0, -self.half, self.half))
        if isinstance(v, str) and v.strip():
            s = self.find_structure(v)
            if s:
                return (s["x"], s["z"])
            o = self.find_agent(v)
            if o:
                return (o["x"], o["z"])
        return None

    def _act_tune_graphics(self, a, action):
        g = self.state["graphics"]
        gm = self.state["game_minutes"]
        if gm - g.get("changed_at", -99999) < GRAPHICS_COOLDOWN_MIN:
            who = self.state["agents"].get(g.get("by") or "", {}).get("name", "someone")
            return f"{who} changed the graphics recently; they need a few hours to settle before changing again."
        changed = []
        for key in ("sun_color", "ambient_color"):
            c = clean_color(action.get(key))
            if c and c != g[key]:
                g[key] = c
                changed.append(f"{key.replace('_', ' ')} {c}")
        for key, lo, hi in (("sun_strength", 0.3, 2.5), ("ambient_strength", 0.3, 2.0), ("sun_tilt", 0, 60), ("hills", 0, 1)):
            if key in action:
                v = round(_num(action.get(key), g[key], lo, hi), 2)
                if v != g[key]:
                    g[key] = v
                    changed.append(f"{key.replace('_', ' ')} {v}")
        sh = str(action.get("shadows", "")).strip().lower()
        if sh in SHADOW_MODES and sh != g["shadows"]:
            g["shadows"] = sh
            changed.append(f"shadows {sh}")
        if "grid" in action:
            v = _truthy(action.get("grid"))
            if v != g["grid"]:
                g["grid"] = v
                changed.append("grid lines " + ("on" if v else "off"))
        mats = action.get("materials")
        if isinstance(mats, dict):
            for name, spec in list(mats.items())[:MAX_MATERIAL_TWEAKS]:
                name = str(name).strip().lower()
                if name not in MATERIALS or not isinstance(spec, dict):
                    continue
                cur = dict(g["materials"].get(name, {}))
                c = clean_color(spec.get("color"))
                if c:
                    cur["color"] = c
                for k, lo, hi in (("roughness", 0, 1), ("metalness", 0, 1), ("glow", 0, 2)):
                    if k in spec:
                        cur[k] = round(_num(spec.get(k), 0.5, lo, hi), 2)
                if cur and cur != g["materials"].get(name):
                    g["materials"][name] = cur
                    changed.append(f"how {name} looks")
        if "effects" in action:
            raw = action.get("effects")
            raw = [raw] if isinstance(raw, (dict, str)) else (raw if isinstance(raw, list) else [])
            eff = []
            for e in raw[:MAX_EFFECTS]:
                if isinstance(e, str):
                    e = {"kind": e}
                if not isinstance(e, dict):
                    continue
                k = str(e.get("kind", "")).strip().lower()
                if k in EFFECT_KINDS and k not in [x["kind"] for x in eff]:
                    eff.append({"kind": k, "color": clean_color(e.get("color")) or None,
                                "amount": round(_num(e.get("amount"), 0.5, 0.1, 1), 2)})
            if eff != g["effects"]:
                g["effects"] = eff
                changed.append("effects: " + (", ".join(x["kind"] for x in eff) or "none"))
        if "ponds" in action:
            raw = action.get("ponds") if isinstance(action.get("ponds"), list) else []
            ponds = []
            for p in raw[:MAX_PONDS]:
                pt = self._point(p.get("at") if isinstance(p, dict) and "at" in p else p)
                if pt and isinstance(p, dict):
                    ponds.append({"x": round(pt[0], 1), "z": round(pt[1], 1), "radius": round(_num(p.get("radius"), 4, 1, 12), 1),
                                  "color": clean_color(p.get("color")) or "#3d8fd1"})
            if ponds != g["ponds"]:
                g["ponds"] = ponds
                changed.append(f"{len(ponds)} pond(s)")
        if "paths" in action:
            raw = action.get("paths") if isinstance(action.get("paths"), list) else []
            paths = []
            for p in raw[:MAX_PATHS]:
                if not isinstance(p, dict):
                    continue
                a0, b0 = self._point(p.get("from")), self._point(p.get("to"))
                if a0 and b0 and (abs(a0[0] - b0[0]) + abs(a0[1] - b0[1])) > 1:
                    paths.append({"from": [round(a0[0], 1), round(a0[1], 1)], "to": [round(b0[0], 1), round(b0[1], 1)],
                                  "width": round(_num(p.get("width"), 1.6, 0.5, 4), 1),
                                  "color": clean_color(p.get("color")) or "#d9c9a3"})
            if paths != g["paths"]:
                g["paths"] = paths
                changed.append(f"{len(paths)} path(s)")
        if not changed:
            return "You thought about changing the graphics, but changed nothing."
        g["by"] = a["id"]
        g["reason"] = clean_text(action.get("reason"), 200)
        g["changed_at"] = gm
        self.state["rev"] += 1
        self.add_event(a["id"], "restyle", f"{a['name']} changed the graphics: {', '.join(changed)}."
                       + (f' "{g["reason"]}"' if g["reason"] else ""))
        return "You changed the graphics: " + ", ".join(changed) + "."

    def _act_request(self, a, action):
        """Ask the Watcher (the human who looks after Olympus) for something they can't make themselves."""
        what = clean_text(action.get("what") or action.get("item") or action.get("thing") or action.get("text"), 160)
        why = clean_text(action.get("why") or action.get("reason"), 400)
        if len(what) < 3:
            return "You meant to ask the Watcher for something, but didn't say what."
        reqs = self.state["requests"]
        mine = [r for r in reqs if r["by"] == a["id"]]
        waiting = [r for r in mine if r["status"] == "open"]
        if len(waiting) >= MAX_OPEN_REQUESTS:
            return (f"You already have {len(waiting)} requests waiting for the Watcher's answer "
                    f"({', '.join(r['what'] for r in waiting)}); wait for those first.")
        gm = self.state["game_minutes"]
        if mine and gm - mine[-1].get("game_minutes", -99999) < REQUEST_COOLDOWN_MIN:
            return "You asked the Watcher for something recently; give them time before asking again."
        key = _request_key(what)
        for r in reqs:
            if r["status"] in ("open", "promised") and _same_request(key, _request_key(r["what"])):
                who = "You" if r["by"] == a["id"] else self.state["agents"].get(r["by"], {}).get("name", "Someone")
                return f'{who} already asked the Watcher for "{r["what"]}"; it is waiting for them.'
        self.state["next_request"] = int(self.state.get("next_request", 0)) + 1
        reqs.append({"id": f"r{self.state['next_request']}", "by": a["id"], "what": what, "why": why,
                     "status": "open", "made": self.stamp(), "game_minutes": gm, "answer": "", "answered": None})
        if len(reqs) > MAX_REQUESTS_KEPT:                  # forget the oldest answered ones, never a waiting one
            done = [r for r in reqs if r["status"] in ("given", "declined")]
            for r in done[: len(reqs) - MAX_REQUESTS_KEPT]:
                reqs.remove(r)
        self.add_event(a["id"], "request", f"{a['name']} asked the Watcher for {what}." + (f' "{why}"' if why else ""))
        return f"You asked the Watcher for {what}. They answer when they can."

    def answer_request(self, rid, status, note=""):
        """The Watcher answers a request from the viewer. Returns the request, or None if there's no such one."""
        with self.lock:
            r = next((x for x in self.state["requests"] if x["id"] == rid), None)
            if r is None or status not in REQUEST_ANSWERS:
                return None
            note = clean_text(note, 400)
            if r["status"] == status and r.get("answer", "") == note:
                return r
            r["status"], r["answer"], r["answered"] = status, note, self.stamp()
            heard, did = REQUEST_ANSWERS[status]
            a = self.state["agents"].get(r["by"])
            if a:
                st = self.stamp()
                text = f'About your request for {r["what"]}: {heard}' + (f" {note}" if note else "")
                a["inbox"].append({"from": "The Watcher", "text": clean_text(text, 600), "direct": True,
                                   "day": st["day"], "time": st["time"]})
                a["inbox"] = a["inbox"][-6:]
            who = a["name"] if a else r["by"]
            self.add_event(r["by"], "request",
                           "The Watcher " + did.format(who=who, what=r["what"]) + "." + (f' "{note}"' if note else ""))
            return r

    def shader_cooldown(self, a, target):
        """None if this god may write a shader for this target now, else the reason not."""
        cur = self.state["shaders"].get(target)
        if not cur:
            return None
        if cur.get("by") == a["id"] and cur.get("status") == "failed":
            return None                                     # fixing your own broken shader is always allowed
        if self.state["game_minutes"] - cur.get("game_minutes", -99999) < SHADER_COOLDOWN_MIN:
            who = self.state["agents"].get(cur.get("by") or "", {}).get("name", "someone")
            return f"{who} gave the {target} a new shader recently; it needs a few hours before another."
        return None

    def save_shader(self, a, target, name, code, reason=""):
        """Store a god's shader (already designed by the mind). The viewer test-compiles it."""
        with self.lock:
            if target not in SHADER_TARGETS:
                return f"There is no '{target}' to shade (only {', '.join(SHADER_TARGETS)})."
            clean, err = validate_shader(code)
            name = clean_text(name or f"{a['name']}'s {target}", 50)
            if err:
                self.remember(a["id"], f"My {target} shader '{name}' was rejected before it ran: {err}.", "shader")
                self.add_event(a["id"], "shader", f"{a['name']}'s {target} shader '{name}' broke the rules ({err}).")
                return f"Your shader was rejected: {err}."
            prev = self.state["shaders"].get(target) or {}
            last_good = prev if prev.get("status") == "ok" else prev.get("last_good")
            if last_good:
                last_good = {k: v for k, v in last_good.items() if k != "last_good"}
            import hashlib
            self.state["shaders"][target] = {
                "target": target, "name": name, "code": clean, "by": a["id"], "reason": clean_text(reason, 200),
                "status": "untested", "error": "", "version": int(prev.get("version", 0)) + 1,
                "hash": hashlib.sha1(clean.encode("utf-8")).hexdigest()[:12], "made": self.stamp(),
                "game_minutes": self.state["game_minutes"], "last_good": last_good}
            self.state["rev"] += 1
            self.add_event(a["id"], "shader", f"{a['name']} wrote a {target} shader: '{name}'.")
            return f"You wrote a {target} shader called '{name}'. It shows once the viewer has tested it."

    def shader_result(self, target, code_hash, ok, error=""):
        """The viewer's report after test-compiling (or timing) a shader."""
        with self.lock:
            cur = self.state["shaders"].get(target)
            if not cur or cur.get("hash") != code_hash:
                return False
            new = "ok" if ok else "failed"
            if cur.get("status") == new and (ok or cur.get("error") == clean_text(error, 300)):
                return True
            cur["status"], cur["error"] = new, ("" if ok else clean_text(error, 300))
            who = self.state["agents"].get(cur["by"], {}).get("name", cur["by"])
            if ok:
                self.add_event(cur["by"], "shader", f"{who}'s {target} shader '{cur['name']}' works and is on screen.")
                self.remember(cur["by"], f"My {target} shader '{cur['name']}' works; it's on screen now.", "shader")
            else:
                self.add_event(cur["by"], "shader", f"{who}'s {target} shader '{cur['name']}' didn't work: {cur['error']}")
                self.remember(cur["by"], f"My {target} shader '{cur['name']}' failed: {cur['error']}. I can fix it.", "shader")
            self.state["rev"] += 1
            return True

    # search_web, plan_project and invent need the network/brain, so mind.py handles them.

    # ------------------------------------------------------------------ views
    def perceive(self, agent_id):
        with self.lock:
            a = self.state["agents"][agent_id]
            c = self.clock()
            near = []
            for o in self.state["agents"].values():
                if o["id"] == agent_id:
                    continue
                d = self.dist(a["x"], a["z"], o["x"], o["z"])
                near.append((d, o))
            near.sort(key=lambda t: t[0])
            places = []
            for s in self.state["structures"].values():
                d = self.dist(a["x"], a["z"], s["x"], s["z"])
                places.append((d, s))
            places.sort(key=lambda t: t[0])
            here = self.nearest_structure(a["x"], a["z"])
            return {
                "clock": c, "self": a, "here": here["name"] if here else None,
                "others": [(round(d), o) for d, o in near],
                "places": [(round(d), s) for d, s in places[:15]],
                "place_count": len(places),
                "environment": dict(self.state["environment"]),
                "graphics": json.loads(json.dumps(self.state["graphics"])),
                "shaders": {k: {"name": v["name"], "by": v["by"], "status": v["status"], "error": v.get("error", "")}
                            for k, v in self.state["shaders"].items()},
                "designs": sorted(self.state["designs"].values(), key=lambda d: -d.get("uses", 0))[:12],
                "design_count": len(self.state["designs"]),
                "my_requests": [{"what": r["what"], "status": r["status"], "answer": r.get("answer", "")}
                                for r in self.state["requests"] if r["by"] == agent_id][-5:],
                "other_requests": [{"by": r["by"], "what": r["what"], "status": r["status"]}
                                   for r in self.state["requests"]
                                   if r["by"] != agent_id and r["status"] in ("open", "promised")][-6:],
            }

    def public_state(self, since_rev=None):
        with self.lock:
            agents = []
            now = time.time()
            for a in self.state["agents"].values():
                said = a.get("said")
                agents.append({
                    "id": a["id"], "name": a["name"], "title": a["title"], "color": a["color"],
                    "x": round(a["x"], 2), "z": round(a["z"], 2), "status": a["status"],
                    "energy": round(a["energy"]), "thought": a["thought"], "goal": a["goal"],
                    "summary": a["summary"], "interests": a["interests"],
                    "project": ({"name": a["project"]["name"], "left": len(a["project"]["remaining"]),
                                 "total": a["project"]["total"]} if a.get("project") else None),
                    "said": said["text"] if said and now - said["real"] < 12 else None,
                    "actions": a["actions_taken"],
                })
            designs = [{"name": d["name"], "inventor": d["inventor"], "description": d["description"],
                        "parts": len(d["parts"]), "uses": d.get("uses", 0), "version": d.get("version", 1),
                        "created": d["created"]} for d in self.state["designs"].values()]
            shaders = {k: {kk: vv for kk, vv in v.items() if kk != "game_minutes"} for k, v in self.state["shaders"].items()}
            out = {"clock": self.clock(), "paused": self.state["paused"], "agents": agents,
                   "environment": self.state["environment"], "designs": designs,
                   "graphics": self.state["graphics"], "shaders": shaders,
                   "requests": [{k: v for k, v in r.items() if k != "game_minutes"} for r in self.state["requests"][-100:]],
                   "rev": self.state["rev"], "half": self.half,
                   "structure_count": len(self.state["structures"])}
            if since_rev is None or int(since_rev) != self.state["rev"]:
                out["structures"] = list(self.state["structures"].values())
            return out
