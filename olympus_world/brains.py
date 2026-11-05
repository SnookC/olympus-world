"""Thinking engines.

- OllamaBrain: the free local model on your PC, used for everyday thoughts.
- GeminiBrain: used only for "big moments" (daily reflections, designing big
  projects), capped per day. Falls back to the local model when the cap is hit.
- FakeBrain: a random stand-in for tests and demos (no AI needed).
"""
import json
import os
import random
import re
import threading
import urllib.error
import urllib.request
from datetime import date


class BrainError(Exception):
    pass


def extract_json(text):
    """Pull the first JSON object out of a model reply."""
    if text is None:
        raise BrainError("empty reply")
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except ValueError:
        pass
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    raise BrainError("reply was not JSON")


def _post_json(url, body, headers=None, timeout=180):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers=dict({"Content-Type": "application/json"}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise BrainError(f"HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise BrainError(f"could not connect: {e.reason}")
    except TimeoutError:
        raise BrainError("timed out")


class OllamaBrain:
    name = "local"

    def __init__(self, url, model):
        self.url = url.rstrip("/")
        self.model = model

    def chat(self, system, user):
        body = {"model": self.model, "stream": False, "format": "json",
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "options": {"temperature": 0.85, "num_ctx": 4096}}
        out = _post_json(self.url + "/api/chat", body)
        return out.get("message", {}).get("content", "")


class GeminiBrain:
    name = "gemini"

    def __init__(self, api_key, model):
        self.api_key = api_key
        self.model = model

    def chat(self, system, user):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {"system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9}}
        out = _post_json(url, body, headers={"x-goog-api-key": self.api_key}, timeout=90)
        try:
            return out["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise BrainError("Gemini reply had no text")


class FakeBrain:
    """Random but valid replies, so the world can run with no AI at all."""
    name = "fake"

    def __init__(self, seed=None):
        self.rnd = random.Random(seed)

    def chat(self, system, user):
        r = self.rnd
        task = re.search(r"TASK:\s*(\w+)", user)
        task = task.group(1) if task else "choose_action"
        if task == "reflect":
            return json.dumps({"diary": r.choice([
                "Today the plain felt very wide. I keep thinking about what should stand here.",
                "I watched the light change and wondered who decided the sky should be this colour.",
                "Built a little, talked a little. The world is quiet but it is ours."]),
                "summary": "A god still finding out what this world is for.",
                "interests": r.sample(["building", "the sky", "conversation", "stone", "the sea", "music"], 3),
                "goal": r.choice(["build a place to gather", "learn about the real world", "make something beautiful"])})
        if task == "blueprint":
            parts = [{"shape": "box", "dx": 0, "y": 0, "dz": 0, "w": 8, "h": 0.5, "d": 8, "material": "marble"}]
            for (dx, dz) in ((-3, -3), (3, -3), (-3, 3), (3, 3)):
                parts.append({"shape": "cylinder", "dx": dx, "y": 0.5, "dz": dz, "w": 0.8, "h": 4, "d": 0.8, "material": "marble"})
            parts.append({"shape": "pyramid", "dx": 0, "y": 4.5, "dz": 0, "w": 9, "h": 2.5, "d": 9, "material": r.choice(["gold", "clay", "bronze"])})
            return json.dumps({"name": r.choice(["Hall of Winds", "Little Temple", "The Gathering Place"]),
                               "purpose": "a place to meet", "parts": parts})
        if task == "invent":
            return json.dumps({"name": r.choice(["Lamp Post", "Fluted Column", "Little Fountain"]),
                               "description": "a small thing worth making twice",
                               "parts": [{"shape": "cylinder", "dx": 0, "y": 0, "dz": 0, "w": 0.3, "h": 3, "d": 0.3, "material": "iron"},
                                         {"shape": "sphere", "dx": 0, "y": 3, "dz": 0, "w": 0.6, "h": 0.6, "d": 0.6,
                                          "material": "glass", "color": "#ffd27a", "glow": True}]})
        if task == "search_reflection":
            return json.dumps({"reflection": "Interesting, though it left me with more questions than answers."})
        kind = r.choice(["move", "build", "say", "wander", "write_diary", "plan_project",
                         "continue_project", "search_web", "build", "say", "invent", "shape_world"])
        act = {"thought": "Let me see what happens.", "goal": "make this place feel alive", "action": kind}
        if kind == "move":
            act["x"], act["z"] = r.randint(-20, 20), r.randint(-20, 20)
        elif kind == "build":
            act.update(name=r.choice(["Stone Circle", "Watchtower", "Garden", "Workshop"]),
                       purpose="because the plain was empty",
                       parts=[{"shape": r.choice(["box", "cylinder", "pyramid", "sphere", "cone", "dome",
                                                  "arch", "stairs", "wedge", "ring", "tree", "bush"]),
                               "dx": r.randint(-3, 3), "y": 0, "dz": r.randint(-3, 3), "rot": r.choice([0, 45, 90]),
                               "w": r.randint(1, 4), "h": r.randint(1, 5), "d": r.randint(1, 4),
                               "material": r.choice(["stone", "wood", "marble", "brick", "glass", "gold"]),
                               "glow": r.random() < 0.2}
                              for _ in range(r.randint(1, 4))]
                       + [{"design": r.choice(["Lamp Post", "Fluted Column", "Little Fountain"]),
                           "dx": r.randint(-4, 4), "dz": r.randint(-4, 4)}])
        elif kind == "invent":
            act["idea"] = "a lamp for dark nights"
        elif kind == "shape_world":
            act.update(weather=r.choice(["clear", "cloudy", "rain", "snow", "mist", "storm"]),
                       sky=r.choice(["#3f6fd8", "#5a8ee8", "#7a5cc0"]), reason="it felt right")
        elif kind == "say":
            act.update(to=r.choice(["Zeus", "Athena", "Hephaestus"]),
                       text=r.choice(["What should we make next?", "Have you seen the light at dusk?",
                                      "I think we need a place to meet.", "Come look at this."]))
        elif kind == "write_diary":
            act["text"] = "A quiet hour. I am still learning the shape of this place."
        elif kind == "plan_project":
            act["idea"] = "a place where we can all gather"
        elif kind == "search_web":
            act["query"] = r.choice(["Greek temple architecture", "how bronze is made", "owls"])
        return json.dumps(act)


class UsageLedger:
    """Counts calls per day so caps survive restarts."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except ValueError:
                self.data = {}

    def _today(self):
        t = date.today().isoformat()
        if self.data.get("date") != t:
            self.data = {"date": t, "gemini": 0, "local": 0, "web": 0, "errors": 0}
        return self.data

    def count(self, key):
        with self.lock:
            return self._today().get(key, 0)

    def add(self, key, n=1):
        with self.lock:
            d = self._today()
            d[key] = d.get(key, 0) + n
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            os.replace(tmp, self.path)

    def snapshot(self):
        with self.lock:
            return dict(self._today())


class Router:
    def __init__(self, local, ledger, gemini=None, gemini_cap=20):
        self.local = local
        self.gemini = gemini
        self.gemini_cap = int(gemini_cap)
        self.ledger = ledger
        self.last_error = None
        self.gemini_error = None
        self.last_brain = None

    def gemini_available(self):
        return self.gemini is not None and self.ledger.count("gemini") < self.gemini_cap

    def _call(self, brain, system, user):
        reply = brain.chat(system, user)
        obj = extract_json(reply)
        self.ledger.add("gemini" if brain.name == "gemini" else "local")
        self.last_brain = brain.name
        if brain.name == "gemini":
            self.gemini_error = None
        else:
            self.last_error = None
        return obj

    def think(self, system, user):
        """Everyday thought: always the local model."""
        try:
            return self._call(self.local, system, user)
        except BrainError as e:
            self.ledger.add("errors")
            self.last_error = f"Local model: {e}"
            raise

    def big(self, system, user):
        """Big moment: Gemini if allowed and under the cap, otherwise local."""
        if self.gemini_available():
            try:
                return self._call(self.gemini, system, user)
            except BrainError as e:
                self.ledger.add("gemini")  # failed calls still count toward the cap
                self.ledger.add("errors")
                self.gemini_error = f"Gemini failed, used the local model instead: {e}"
        return self.think(system, user)
