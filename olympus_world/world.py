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
MAX_DESIGN_PARTS = 40
MAX_DESIGNS = 200
MAX_PARTS_TOTAL = 12000
PARTS_PER_CONTINUE = 10
RESHAPE_COOLDOWN_MIN = 360   # game minutes between changes to the world's look
HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
ENV_DEFAULT = {"weather": "clear", "sky": "#3f6fd8", "horizon": "#cdd8ff", "ground": "#aaa4ea",
               "fog": 0.2, "clouds": 0.5, "by": None, "reason": "", "changed_at": -99999}
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
            "events": [], "diaries": [], "searches": [], "talks": [],
        }

    def _upgrade(self):
        s = self.state
        for key, default in (("events", []), ("diaries", []), ("searches", []),
                             ("talks", []), ("structures", {}), ("rev", 0), ("paused", False),
                             ("designs", {})):
            s.setdefault(key, default)
        env = s.setdefault("environment", {})
        for k, v in ENV_DEFAULT.items():
            env.setdefault(k, v)
        for a in s["agents"].values():
            a.setdefault("recent", [])
            a.setdefault("inbox", [])
            a.setdefault("actions_taken", 0)
            a.setdefault("rest_until", None)

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
                return s["x"], s["z"] + 2.5, s["name"]
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

    def free_site(self, near_x, near_z, min_gap=11.0):
        """Find an open spot near a point, away from other structures."""
        rnd = random.Random(int(self.state["game_minutes"]) + len(self.state["structures"]))
        for radius in (6, 10, 14, 18, 24, 30):
            for _ in range(24):
                ang = rnd.random() * 2 * math.pi
                x, z = self.clamp_xy(near_x + math.cos(ang) * radius, near_z + math.sin(ang) * radius)
                if all(self.dist(x, z, s["x"], s["z"]) >= min_gap for s in self.state["structures"].values()):
                    return round(x, 1), round(z, 1)
        return self.clamp_xy(near_x + 8, near_z + 8)

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
        self.walk_to(a, x, z)
        self.add_event(a["id"], "move", f"{a['name']} walks toward {label}.")
        return f"You started walking toward {label}."

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

    def _site_for(self, a, action, existing):
        if existing:
            return existing["x"], existing["z"]
        if "x" in action and "z" in action:
            x = _num(action.get("x"), a["x"], -self.half, self.half)
            z = _num(action.get("z"), a["z"], -self.half, self.half)
            return self.clamp_xy(x, z)
        return self.free_site(a["x"], a["z"])

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
        sx, sz = self._site_for(a, action, existing)
        if self.dist(a["x"], a["z"], sx, sz) > REACH + 6:
            fixed = dict(action, x=sx, z=sz)
            self.walk_to(a, sx + 2, sz + 3, pending=fixed)
            return f"You head to the building site for '{name}'."
        s = self._place(a, name, clean_text(action.get("purpose"), 200), sx, sz, parts, existing)
        self._count_uses(used)
        extra = f" using {', '.join(used)}" if used else ""
        if unknown:
            extra += f" (no invention called {', '.join(unknown)} exists)"
        return f"You built {len(parts)} part(s) of '{s['name']}'{extra}."

    def _place(self, a, name, purpose, sx, sz, parts, existing):
        if existing is None:
            sid = uuid.uuid4().hex[:8]
            existing = {"id": sid, "name": name, "purpose": purpose or "", "builder": a["id"],
                        "x": round(sx, 2), "z": round(sz, 2), "parts": [],
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
            if existing:
                sx, sz = existing["x"], existing["z"]
            else:
                sx, sz = self.free_site(a["x"], a["z"])
            a["project"] = {"name": name, "idea": clean_text(idea, 200),
                            "purpose": clean_text(blueprint.get("purpose"), 200),
                            "x": sx, "z": sz, "remaining": parts, "total": len(parts)}
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
        batch, pr["remaining"] = pr["remaining"][:PARTS_PER_CONTINUE], pr["remaining"][PARTS_PER_CONTINUE:]
        if self.total_parts() + len(batch) > MAX_PARTS_TOTAL:
            return "The world is too full to build more right now."
        existing = self.find_structure(pr["name"])
        s = self._place(a, pr["name"], pr.get("purpose"), pr["x"], pr["z"], batch, existing)
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
                "designs": sorted(self.state["designs"].values(), key=lambda d: -d.get("uses", 0))[:12],
                "design_count": len(self.state["designs"]),
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
            out = {"clock": self.clock(), "paused": self.state["paused"], "agents": agents,
                   "environment": self.state["environment"], "designs": designs,
                   "rev": self.state["rev"], "half": self.half,
                   "structure_count": len(self.state["structures"])}
            if since_rev is None or int(since_rev) != self.state["rev"]:
                out["structures"] = list(self.state["structures"].values())
            return out
