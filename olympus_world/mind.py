"""Minds: how each god perceives, decides, reflects and learns.

The Engine runs forever: it picks whose turn it is, asks their brain what
they do next, and applies it to the world. Nobody gives them tasks.
"""
import json
import time
from collections import Counter

from . import websearch
from .brains import BrainError
from .world import (MATERIALS, SHAPES, WEATHERS, MAX_PARTS_PER_BUILD, MAX_PARTS_PER_PROJECT,
                    MAX_DESIGN_PARTS, clean_text)

SYSTEM_TEMPLATE = """You are {name}, {title}. {persona}
You live in Olympus, a small 3D world that began as a bare, flat plain under an open sky.
Nothing exists here unless someone builds it: no buildings, shops, roads or entertainment
until a resident decides to make them. Nobody gives you tasks or instructions. You decide
how to spend your time, what you care about, and what to create. You can look things up
about the real human world, but you live here.
Stay in character. Be specific and concrete. Reply with ONE JSON object and nothing else."""

PARTS_HELP = """A part: {{"shape":"box","dx":0,"y":0,"dz":0,"w":4,"h":3,"d":1,"material":"stone","rot":0,"color":"#c0a060","glow":false}}
  dx/dz = offset from the centre, y = height of the part's bottom (0 = ground), w/h/d = size (0.1 to 16), rot = turn in degrees.
  shapes: {shapes}  (arch = wall with a doorway, stairs = steps rising toward -z, wedge = ramp/sloped roof, ring = upright hoop, tree/bush = plants)
  materials: {materials}. "color" (optional, any #rrggbb) tints it. "glow":true makes it shine at night.
  An invention can be a part too: {{"design":"<invention name>","dx":0,"y":0,"dz":0,"scale":1,"rot":0}}"""

ACTIONS_HELP = """ACTIONS (choose exactly one):
{{"action":"move","to":"<place or being name>"}}   or   {{"action":"move","x":0,"z":0}}
{{"action":"say","to":"<name or empty for everyone nearby>","text":"..."}}
{{"action":"build","name":"<place name>","purpose":"...","x":0,"z":0,"parts":[ up to {maxparts} parts ]}}
    use an existing place's name to add to it (anyone may add to any place); omit x,z to let the world pick an open spot
{{"action":"plan_project","idea":"<something big you want to make>"}}   (designs a large detailed build you then construct over time)
{{"action":"continue_project"}}   (build the next section of your project)
{{"action":"invent","idea":"<a reusable object, e.g. an ornate column, a fountain, a lamp post>"}}   (designs it once; then anyone can build it by name)
{{"action":"shape_world","weather":"<{weathers}>","sky":"#rrggbb","horizon":"#rrggbb","ground":"#rrggbb","fog":0.2,"clouds":0.5,"reason":"..."}}   (change how the whole world looks; include only what you change)
{{"action":"search_web","query":"..."}}   (read about the real human world on Wikipedia; read-only)
{{"action":"write_diary","text":"..."}}
{{"action":"demolish","name":"<a place you built>"}}
{{"action":"rest"}}
{{"action":"wander"}}
""" + PARTS_HELP + """
Always also include "thought" (a short private thought) and "goal" (what you're working toward right now)."""


HABIT_WINDOW = 8          # recent choices checked for being stuck
STALE_GOAL_DAYS = 3       # game days on one goal before they're nudged to rethink it
FRESH_ACTIONS = ("plan_project", "invent", "shape_world", "search_web", "say")


def habit_of(act):
    """A short signature of one choice, e.g. 'move:hephaestus' or 'build:athenatemple'."""
    kind = str(act.get("action", "")).strip().lower().replace(" ", "_")
    tgt = act.get("to") or act.get("name") or act.get("idea") or ""
    if kind == "move" and not tgt:
        try:
            tgt = f"{round(float(act.get('x', 0)) / 5)},{round(float(act.get('z', 0)) / 5)}"
        except (TypeError, ValueError):
            tgt = ""
    return f"{kind}:{str(tgt).strip().lower()[:40]}"


def stuck_lines(a, day):
    """Plain-English nudges when a god keeps repeating itself or clings to one goal."""
    out = []
    h = list(a.get("habits") or [])[-HABIT_WINDOW:]
    if len(h) >= 6:
        top, n = Counter(h).most_common(1)[0]
        walking = sum(1 for x in h if x.startswith(("move:", "wander:")))
        kind, _, tgt = top.partition(":")
        if n >= 5:
            what = f"{kind} {tgt}".strip()
            out.append(f"YOU ARE STUCK: {n} of your last {len(h)} choices were '{what}'. It isn't getting anywhere. "
                       "Choose something DIFFERENT now.")
        elif walking >= 6:
            out.append(f"YOU ARE STUCK: {walking} of your last {len(h)} choices were just walking. "
                       "Do something where you are: build, invent, talk, change the weather, or look something up.")
    kinds = {x.split(":", 1)[0] for x in (a.get("habits") or [])[-12:]}
    fresh = [k for k in FRESH_ACTIONS if k not in kinds]
    if fresh and len(a.get("habits") or []) >= 6:
        out.append("THINGS YOU HAVEN'T DONE LATELY: " + ", ".join(fresh))
    since = a.get("goal_since") or 0
    if a.get("goal") and since and day - since >= STALE_GOAL_DAYS:
        out.append(f"You've had the same goal since day {since} ({day - since} days). If it isn't moving, "
                   'set a NEW "goal": something Olympus doesn\'t have yet.')
    return out


def set_goal(a, goal, day):
    goal = clean_text(goal, 200)
    if goal and goal != a.get("goal"):
        a["goal"] = goal
        a["goal_since"] = day


def parts_help():
    return PARTS_HELP.format(shapes=", ".join(SHAPES), materials=", ".join(MATERIALS))


def build_action_prompt(world, agent_id):
    p = world.perceive(agent_id)
    a = p["self"]
    c = p["clock"]
    lines = ["TASK: choose_action", ""]
    lines.append(f"TIME: Day {c['day']}, {c['time']} ({c['part']})")
    where = f'near "{p["here"]}"' if p["here"] else "in open ground"
    lines.append(f"YOU: at ({a['x']:.0f}, {a['z']:.0f}), {where}. Energy {a['energy']:.0f}/100.")
    if a["energy"] < 25:
        lines.append("You feel very tired.")
    if a.get("summary"):
        lines.append(f"WHO YOU'VE BECOME: {a['summary']}")
    if a.get("interests"):
        lines.append("YOUR INTERESTS: " + ", ".join(a["interests"]))
    if a.get("goal"):
        lines.append(f"YOUR CURRENT GOAL: {a['goal']}")
    lines.append("")
    if p["others"]:
        lines.append("OTHER BEINGS:")
        for d, o in p["others"]:
            doing = o["status"]
            if o.get("project"):
                doing += f", working on '{o['project']['name']}'"
            lines.append(f"- {o['name']} ({o['title']}): {d} units away, {doing}")
    if p["places"]:
        lines.append(f"PLACES IN THE WORLD ({p['place_count']} total, nearest first):")
        for d, s in p["places"]:
            by = world.state["agents"].get(s["builder"], {}).get("name", s["builder"])
            purpose = f" - {s['purpose']}" if s.get("purpose") else ""
            done = " (FINISHED: nobody can add to it)" if s.get("finished") else ""
            lines.append(f'- "{s["name"]}" by {by}, {d} units away, {len(s["parts"])} parts{done}{purpose}')
    else:
        lines.append("PLACES IN THE WORLD: none yet. The plain is empty.")
    env = p["environment"]
    look = f"WORLD LOOK: weather {env['weather']}, sky {env['sky']}, horizon {env['horizon']}, ground {env['ground']}"
    if env.get("by"):
        who = world.state["agents"].get(env["by"], {}).get("name", env["by"])
        look += f" (last changed by {who}" + (f": {env['reason']}" if env.get("reason") else "") + ")"
    lines.append(look)
    if p["designs"]:
        lines.append(f"INVENTIONS anyone can build ({p['design_count']} total):")
        for d in p["designs"]:
            by = world.state["agents"].get(d["inventor"], {}).get("name", d["inventor"])
            lines.append(f'- "{d["name"]}" by {by}, {len(d["parts"])} parts, used {d.get("uses", 0)} times - {d["description"]}')
    else:
        lines.append("INVENTIONS: none yet.")
    if a.get("project"):
        pr = a["project"]
        lines.append(f"YOUR PROJECT: '{pr['name']}' - {len(pr['remaining'])} of {pr['total']} parts still to build (use continue_project).")
    if a["inbox"]:
        lines.append("")
        lines.append("YOU HEARD:")
        for m in a["inbox"]:
            to = "to you" if m["direct"] else "nearby"
            lines.append(f'- {m["from"]} ({to}, Day {m["day"]} {m["time"]}): "{m["text"]}"')
    if a["recent"]:
        lines.append("")
        lines.append("RECENT MEMORIES (oldest first):")
        lines.extend("- " + r for r in a["recent"][-14:])
    nudges = stuck_lines(a, c["day"])
    if nudges:
        lines.append("")
        lines.extend(nudges)
    lines.append("")
    lines.append(ACTIONS_HELP.format(maxparts=MAX_PARTS_PER_BUILD, shapes=", ".join(SHAPES),
                                     materials=", ".join(MATERIALS), weathers="|".join(WEATHERS)))
    return "\n".join(lines)


def system_for(agent):
    return SYSTEM_TEMPLATE.format(name=agent["name"], title=agent["title"], persona=agent["persona"])


class Engine:
    def __init__(self, world, router, settings, search_fn=None):
        self.world = world
        self.router = router
        self.settings = settings
        self.search_fn = search_fn or websearch.search
        self.web_cap = int(settings.get("web_daily_cap", 30))
        self.pause_s = float(settings.get("think_pause_seconds", 3))
        self.order = list(world.state["agents"].keys())
        self.turn = 0
        self.current = None
        self.stop = False

    # ------------------------------------------------------------- scheduling
    def pick_agent(self):
        with self.world.lock:
            agents = self.world.state["agents"]
            for a in agents.values():          # nobody is mid-thought between turns: free any stuck god
                if a["status"] in ("thinking", "reading") and a["id"] != self.current:
                    a["status"] = "idle"
            free = [a for a in agents.values() if not self.world.is_busy(a)]
            if not free:
                return None
            # someone spoke to you directly? you get to answer first
            for a in free:
                if any(m["direct"] for m in a["inbox"]):
                    return a["id"]
            for _ in range(len(self.order)):
                aid = self.order[self.turn % len(self.order)]
                self.turn += 1
                if agents[aid] in free:
                    return aid
        return None

    def needs_reflection(self, aid):
        a = self.world.state["agents"][aid]
        day = self.world.clock()["day"]
        return day - 1 > a.get("last_day_reflected", 0) and a["actions_taken"] > 0

    def run_once(self):
        """One decision by one god. Returns a short description or None."""
        if self.world.state["paused"]:
            return None
        aid = self.pick_agent()
        if aid is None:
            return None
        self.current = aid
        try:
            if self.needs_reflection(aid):
                return self.reflect(aid)
            return self.decide(aid)
        finally:
            self.current = None
            with self.world.lock:
                a = self.world.state["agents"][aid]
                if a["status"] == "thinking":
                    a["status"] = "idle"

    def loop(self):
        while not self.stop:
            try:
                did = self.run_once()
            except BrainError:
                time.sleep(15)
                continue
            except Exception as e:  # keep the world alive no matter what
                self.router.last_error = f"Engine: {type(e).__name__}: {e}"
                time.sleep(5)
                continue
            time.sleep(self.pause_s if did else 1.0)

    # ------------------------------------------------------------- decisions
    def decide(self, aid):
        w = self.world
        with w.lock:
            a = w.state["agents"][aid]
            a["status"] = "thinking"
            system = system_for(a)
            user = build_action_prompt(w, aid)
            heard = list(a["inbox"])
        act = self.router.think(system, user)
        with w.lock:
            a = w.state["agents"][aid]
            a["status"] = "idle"
            a["thought"] = clean_text(act.get("thought"), 300)
            if act.get("goal"):
                set_goal(a, act.get("goal"), w.clock()["day"])
            a["habits"] = (list(a.get("habits") or []) + [habit_of(act)])[-12:]
            # messages they've now heard leave the inbox but stay in memory
            for m in heard:
                w.remember(aid, f'{m["from"]} said: "{m["text"]}"', "heard")
            a["inbox"] = [m for m in a["inbox"] if m not in heard]
        kind = str(act.get("action", "")).strip().lower()
        if kind == "search_web":
            result = self.do_search(aid, act.get("query"))
        elif kind == "plan_project":
            result = self.do_plan(aid, act.get("idea"))
        elif kind == "invent":
            result = self.do_invent(aid, act.get("idea") or act.get("name"))
        else:
            result = w.apply_action(aid, act)
        with w.lock:
            note = f"I decided to {kind or 'do nothing'}. {result}"
            if act.get("thought"):
                note = f'Thought: "{clean_text(act["thought"], 160)}" -> {note}'
            w.remember(aid, note, "action")
        return f"{aid}: {kind} -> {result}"

    def do_search(self, aid, query):
        w = self.world
        query = clean_text(query, 200)
        if not query:
            return "You meant to look something up but couldn't think what."
        if self.router.ledger.count("web") >= self.web_cap:
            return "The window to the human world is closed for today (daily search limit reached)."
        with w.lock:
            a = w.state["agents"][aid]
            a["status"] = "reading"
            w.add_event(aid, "search", f'{a["name"]} is looking up "{query}".')
        self.router.ledger.add("web")
        try:
            page = self.search_fn(query)
        except websearch.SearchError as e:
            with w.lock:
                w.add_search(aid, query, "", "", f"Couldn't find anything ({e}).", ok=False)
                w.state["agents"][aid]["status"] = "idle"
            return f'You searched for "{query}" but found nothing ({e}).'
        with w.lock:
            a = w.state["agents"][aid]
            system = system_for(a)
        user = ("TASK: search_reflection\n"
                f'You looked up "{query}" and read this page from the human world.\n'
                f"TITLE: {page['title']}\n\n{page['text']}\n\n"
                'Reply as JSON: {"reflection":"1-2 sentences in your own voice about what you made of it",'
                ' "takeaway":"one fact or idea you want to remember"}')
        try:
            r = self.router.think(system, user)
            reflection = clean_text(r.get("reflection"), 500)
            takeaway = clean_text(r.get("takeaway"), 200)
        except BrainError:
            reflection, takeaway = "", ""
        with w.lock:
            w.add_search(aid, query, page["title"], page["url"], reflection)
            w.remember(aid, f'Read "{page["title"]}" on the human internet. {takeaway or reflection}', "search")
            w.state["agents"][aid]["status"] = "idle"
        return f'You read "{page["title"]}".'

    def do_plan(self, aid, idea):
        w = self.world
        idea = clean_text(idea, 200)
        if not idea:
            return "You couldn't settle on an idea."
        with w.lock:
            a = w.state["agents"][aid]
            if a.get("project"):
                return f"You already have a project, '{a['project']['name']}'. Finish it first with continue_project."
            a["status"] = "thinking"
            system = system_for(a)
            existing = ", ".join(f'"{s["name"]}"' for s in w.state["structures"].values()) or "nothing yet"
            inventions = self._inventions_line()
        user = ("TASK: blueprint\n"
                f"You want to make: {idea}\n"
                f"Already in the world: {existing}\n"
                f"{inventions}\n"
                f"Design it as up to {MAX_PARTS_PER_PROJECT} 3D parts around a centre point. Make it detailed and beautiful: "
                "think like an architect - foundation and steps, walls with arches for doorways, columns, "
                "a roof, trim, windows of glass, lamps that glow at night, plants and paths around it. "
                "Units are roughly metres; a god is about 2 tall. Offsets can reach 30 from the centre.\n"
                + parts_help() + "\n"
                'Reply as JSON: {"name":"...","purpose":"why it exists","parts":[ ... ]}')
        try:
            bp = self.router.big(system, user)
        except BrainError:
            with w.lock:
                w.state["agents"][aid]["status"] = "idle"
            raise
        with w.lock:
            w.state["agents"][aid]["status"] = "idle"
            return w.start_project(w.state["agents"][aid], idea, bp)

    def _inventions_line(self):
        ds = list(self.world.state["designs"].values())
        if not ds:
            return "Inventions you could reuse: none yet."
        return "Inventions you could reuse as parts: " + "; ".join(
            f'"{d["name"]}" ({d["description"][:60]})' for d in ds[:15])

    def do_invent(self, aid, idea):
        """Design a reusable object once (a 'big moment'); anyone can then build it by name."""
        w = self.world
        idea = clean_text(idea, 200)
        if not idea:
            return "You couldn't settle on what to invent."
        with w.lock:
            a = w.state["agents"][aid]
            a["status"] = "thinking"
            system = system_for(a)
            inventions = self._inventions_line()
        user = ("TASK: invent\n"
                f"You are inventing: {idea}\n"
                "It is a reusable object others can place in their own builds (like a column, statue, "
                "fountain, lamp, bench, tree arrangement, window, gate). Design it centred on (0,0), "
                f"standing on the ground, using up to {MAX_DESIGN_PARTS} parts. Use fine detail: small parts, "
                "rotation, colours and glow where it makes sense.\n"
                f"{inventions}\n"
                + parts_help() + "\n"
                'Reply as JSON: {"name":"short name","description":"what it is, one sentence","parts":[ ... ]}')
        try:
            design = self.router.big(system, user)
        finally:
            with w.lock:
                w.state["agents"][aid]["status"] = "idle"
        return w.save_design(w.state["agents"][aid], idea, design)

    def reflect(self, aid):
        """Once per game day: a diary entry and an updated sense of self (a 'big moment')."""
        w = self.world
        with w.lock:
            a = w.state["agents"][aid]
            a["status"] = "thinking"
            system = system_for(a)
            day = w.clock()["day"] - 1
            memories = "\n".join("- " + r for r in a["recent"][-30:]) or "- (nothing much)"
            prior = a.get("summary") or "(you haven't thought about it yet)"
            mine = [s for s in w.state["structures"].values() if aid in s.get("contributors", [s.get("builder")])]
            worked = "\n".join(f'- "{s["name"]}": {len(s["parts"])} parts' + (" (FINISHED)" if s.get("finished") else "")
                               for s in mine) or "- (nothing yet)"
            have = ", ".join(s["name"] for s in w.state["structures"].values()) or "nothing yet"
            goal_now, since = a.get("goal") or "(none)", a.get("goal_since") or 0
        user = ("TASK: reflect\n"
                f"Day {day} has ended. Here is what you remember of it:\n{memories}\n\n"
                f"How you described yourself before: {prior}\n"
                f"Your goal so far: {goal_now}" + (f" (since day {since})" if since else "") + "\n"
                f"Places you've worked on:\n{worked}\n"
                f"Everything that exists in Olympus: {have}\n\n"
                "Olympus needs variety. If your goal's place is FINISHED, or you've chased the same goal for days, "
                "choose a NEW goal for tomorrow: something Olympus doesn't have yet (for example a market, a road, "
                "a garden, a theatre, a bath house, an invention, or a change in the weather), or something with "
                "another god. Don't just repeat yesterday.\n\n"
                "Write tonight's diary entry in your own voice (3-6 sentences, honest, specific, "
                "mention real things that happened). Then update who you are becoming.\n"
                'Reply as JSON: {"diary":"...","summary":"who you are now, max 60 words",'
                '"interests":["up to 6 short things you care about"],"goal":"what you want to do next"}')
        r = self.router.big(system, user)
        with w.lock:
            a = w.state["agents"][aid]
            a["status"] = "idle"
            a["last_day_reflected"] = day
            if r.get("diary"):
                w.add_diary(aid, f"Day {day}: {clean_text(r['diary'], 1100)}", kind="reflection")
            if r.get("summary"):
                a["summary"] = clean_text(r["summary"], 400)
            if isinstance(r.get("interests"), list):
                a["interests"] = [clean_text(i, 40) for i in r["interests"][:6] if i]
            if r.get("goal"):
                set_goal(a, r["goal"], day + 1)
            a["habits"] = []                       # a new day: a fresh start
            w.remember(aid, f"Reflected on day {day}. Goal now: {a['goal']}", "reflection")
        return f"{aid}: reflected on day {day}"
