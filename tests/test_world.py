import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from olympus_world import brains, websearch
from olympus_world.config import DEFAULTS
from olympus_world.mind import Engine, build_action_prompt
from olympus_world.server import App, make_handler
from olympus_world.world import MAX_PARTS_PER_BUILD, World, clean_part, expand_parts


def fake_search(q):
    return {"title": "Owl", "url": "https://en.wikipedia.org/wiki/Owl", "text": "Owls are birds of prey."}


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.settings = dict(DEFAULTS)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def world(self):
        return World(self.dir, self.settings)


class TestParts(unittest.TestCase):
    def test_clamps_and_defaults(self):
        p = clean_part({"shape": "dragon", "material": "lava", "w": 999, "h": -5, "y": -3, "dx": 500})
        self.assertEqual(p["shape"], "box")
        self.assertEqual(p["material"], "stone")
        self.assertEqual(p["w"], 16.0)
        self.assertEqual(p["h"], 0.1)
        self.assertEqual(p["y"], 0)
        self.assertEqual(p["dx"], 30)

    def test_rejects_garbage(self):
        self.assertIsNone(clean_part("a wall"))
        p = clean_part({"w": "nan", "h": "abc"})
        self.assertEqual(p["w"], 1)
        self.assertEqual(p["h"], 1)


class TestWorld(Base):
    def test_new_world_has_three_gods_and_nothing_built(self):
        w = self.world()
        self.assertEqual(set(w.state["agents"]), {"zeus", "hephaestus", "athena"})
        self.assertEqual(w.state["structures"], {})

    def test_build_nearby_places_parts(self):
        w = self.world()
        z = w.state["agents"]["zeus"]
        r = w.apply_action("zeus", {"action": "build", "name": "Altar", "x": z["x"] + 1, "z": z["z"] + 1,
                                    "parts": [{"shape": "box", "w": 2, "h": 1, "d": 2, "material": "marble"}]})
        self.assertIn("built", r)
        s = w.find_structure("altar")
        self.assertEqual(len(s["parts"]), 1)
        self.assertEqual(w.state["rev"], 1)

    def test_build_far_away_walks_then_builds_on_arrival(self):
        w = self.world()
        w.apply_action("zeus", {"action": "build", "name": "Far Tower", "x": 30, "z": 30,
                                "parts": [{"shape": "cylinder", "w": 2, "h": 6, "d": 2}]})
        self.assertIsNone(w.find_structure("Far Tower"))
        self.assertEqual(w.state["agents"]["zeus"]["status"], "walking")
        for _ in range(200):
            w.step(0.5)
        self.assertIsNotNone(w.find_structure("Far Tower"))
        self.assertEqual(w.state["agents"]["zeus"]["status"], "idle")

    def test_parts_per_build_capped(self):
        w = self.world()
        w.apply_action("zeus", {"action": "build", "name": "Big", "x": 0, "z": 0,
                                "parts": [{"w": 1}] * 50})
        self.assertEqual(len(w.find_structure("Big")["parts"]), MAX_PARTS_PER_BUILD)

    def test_others_can_add_to_a_place(self):
        w = self.world()
        w.apply_action("zeus", {"action": "build", "name": "Hall", "x": 0, "z": 0, "parts": [{"w": 1}]})
        w.state["agents"]["athena"]["x"] = 1
        w.state["agents"]["athena"]["z"] = 1
        w.apply_action("athena", {"action": "build", "name": "hall", "parts": [{"w": 2}]})
        s = w.find_structure("Hall")
        self.assertEqual(len(s["parts"]), 2)
        self.assertIn("athena", s["contributors"])

    def test_cannot_demolish_someone_elses_place(self):
        w = self.world()
        w.apply_action("zeus", {"action": "build", "name": "Throne", "x": 0, "z": 0, "parts": [{"w": 1}]})
        r = w.apply_action("athena", {"action": "demolish", "name": "Throne"})
        self.assertIn("isn't yours", r)
        self.assertIsNotNone(w.find_structure("Throne"))
        w.apply_action("zeus", {"action": "demolish", "name": "Throne"})
        self.assertIsNone(w.find_structure("Throne"))

    def test_say_reaches_inbox(self):
        w = self.world()
        w.state["agents"]["athena"]["x"] = 1
        w.apply_action("zeus", {"action": "say", "to": "Athena", "text": "Hello"})
        self.assertEqual(w.state["agents"]["athena"]["inbox"][-1]["text"], "Hello")
        self.assertTrue(w.state["agents"]["athena"]["inbox"][-1]["direct"])
        self.assertEqual(len(w.state["talks"]), 1)

    def test_unknown_action_wanders(self):
        w = self.world()
        r = w.apply_action("zeus", {"action": "fly_to_the_moon"})
        self.assertIn("not something you can do", r)

    def test_rest_and_wake(self):
        w = self.world()
        w.state["agents"]["zeus"]["energy"] = 10
        w.apply_action("zeus", {"action": "rest"})
        self.assertEqual(w.state["agents"]["zeus"]["status"], "resting")
        for _ in range(400):
            w.step(1.0)
        self.assertEqual(w.state["agents"]["zeus"]["status"], "idle")

    def test_save_and_reload(self):
        w = self.world()
        w.apply_action("zeus", {"action": "build", "name": "Keep", "x": 0, "z": 0, "parts": [{"w": 1}]})
        w.add_diary("zeus", "Dear diary")
        w.save()
        w2 = self.world()
        self.assertIsNotNone(w2.find_structure("Keep"))
        self.assertEqual(w2.state["diaries"][-1]["text"], "Dear diary")

    def test_stays_inside_world(self):
        w = self.world()
        w.apply_action("zeus", {"action": "move", "x": 9999, "z": -9999})
        a = w.state["agents"]["zeus"]
        self.assertLess(abs(a["tx"]), w.half)
        self.assertLess(abs(a["tz"]), w.half)

    def test_pause_stops_time(self):
        w = self.world()
        w.state["paused"] = True
        t = w.state["game_minutes"]
        w.step(5)
        self.assertEqual(w.state["game_minutes"], t)


class TestBrains(Base):
    def test_extract_json_variants(self):
        self.assertEqual(brains.extract_json('{"a":1}')["a"], 1)
        self.assertEqual(brains.extract_json('```json\n{"a":2}\n```')["a"], 2)
        self.assertEqual(brains.extract_json('Sure! {"a":"x}y"} hope that helps')["a"], "x}y")
        with self.assertRaises(brains.BrainError):
            brains.extract_json("no json here")

    def test_gemini_cap_falls_back_to_local(self):
        ledger = brains.UsageLedger(os.path.join(self.dir, "u.json"))

        class Named(brains.FakeBrain):
            def __init__(self, name):
                super().__init__(1)
                self.name = name
        r = brains.Router(Named("local"), ledger, Named("gemini"), gemini_cap=2)
        for _ in range(5):
            r.big("s", "TASK: reflect")
        self.assertEqual(ledger.count("gemini"), 2)
        self.assertEqual(ledger.count("local"), 3)

    def test_gemini_error_falls_back(self):
        ledger = brains.UsageLedger(os.path.join(self.dir, "u.json"))

        class Broken:
            name = "gemini"

            def chat(self, s, u):
                raise brains.BrainError("HTTP 400")
        r = brains.Router(brains.FakeBrain(1), ledger, Broken(), gemini_cap=5)
        out = r.big("s", "TASK: reflect")
        self.assertIn("diary", out)
        self.assertIn("local model instead", r.gemini_error)

    def test_ollama_request_shape(self):
        seen = {}

        def fake_post(url, body, headers=None, timeout=0):
            seen["url"], seen["body"] = url, body
            return {"message": {"content": '{"action":"rest"}'}}
        old = brains._post_json
        brains._post_json = fake_post
        try:
            out = brains.OllamaBrain("http://127.0.0.1:11434/", "qwen2.5:7b").chat("sys", "usr")
        finally:
            brains._post_json = old
        self.assertEqual(seen["url"], "http://127.0.0.1:11434/api/chat")
        self.assertEqual(seen["body"]["format"], "json")
        self.assertIn("rest", out)

    def test_gemini_request_shape_and_key_in_header_not_url(self):
        seen = {}

        def fake_post(url, body, headers=None, timeout=0):
            seen["url"], seen["headers"] = url, headers
            return {"candidates": [{"content": {"parts": [{"text": '{"ok":1}'}]}}]}
        old = brains._post_json
        brains._post_json = fake_post
        try:
            brains.GeminiBrain("SECRET", "gemini-2.5-flash-lite").chat("s", "u")
        finally:
            brains._post_json = old
        self.assertNotIn("SECRET", seen["url"])
        self.assertEqual(seen["headers"]["x-goog-api-key"], "SECRET")


class TestWebsearch(unittest.TestCase):
    def test_search_parses(self):
        def fetch(url):
            if "api.php" in url:
                return {"query": {"search": [{"title": "Barn owl"}]}}
            return {"title": "Barn owl", "extract": "A bird.",
                    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Barn_owl"}}}
        r = websearch.search("owls", fetch=fetch)
        self.assertEqual(r["title"], "Barn owl")
        self.assertEqual(r["text"], "A bird.")

    def test_no_results(self):
        with self.assertRaises(websearch.SearchError):
            websearch.search("zzzz", fetch=lambda u: {"query": {"search": []}})


class TestMind(Base):
    def make(self):
        w = self.world()
        ledger = brains.UsageLedger(os.path.join(self.dir, "usage.json"))
        r = brains.Router(brains.FakeBrain(3), ledger)
        return w, Engine(w, r, self.settings, search_fn=fake_search)

    def test_prompt_mentions_empty_world_and_actions(self):
        w, _ = self.make()
        p = build_action_prompt(w, "zeus")
        self.assertIn("none yet", p)
        self.assertIn('"action":"build"', p)
        self.assertIn("Athena", p)

    def test_many_turns_stay_healthy(self):
        w, e = self.make()
        for _ in range(300):
            e.run_once()
            for _ in range(10):
                w.step(0.5)
            w.state["game_minutes"] += 4
        self.assertIsNone(e.router.last_error)
        self.assertGreater(len(w.state["events"]), 50)
        self.assertGreater(w.total_parts(), 0)
        # day rolled over, so each god should have reflected at least once
        refl = [d for d in w.state["diaries"] if d["kind"] == "reflection"]
        self.assertGreaterEqual(len({d["agent"] for d in refl}), 2)

    def test_search_cap(self):
        w, e = self.make()
        e.web_cap = 1
        e.do_search("zeus", "owls")
        r = e.do_search("zeus", "more owls")
        self.assertIn("limit", r)
        self.assertEqual(len(w.state["searches"]), 1)

    def test_direct_message_gets_priority(self):
        w, e = self.make()
        w.state["agents"]["hephaestus"]["inbox"].append(
            {"from": "Zeus", "text": "hi", "direct": True, "day": 1, "time": "08:00"})
        self.assertEqual(e.pick_agent(), "hephaestus")

    def test_paused_world_does_nothing(self):
        w, e = self.make()
        w.state["paused"] = True
        self.assertIsNone(e.run_once())


class TestServer(Base):
    def test_state_and_journal_endpoints(self):
        app = App(self.dir, self.settings, fake=True, search_fn=fake_search)
        for _ in range(20):
            app.engine.run_once()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            st = json.loads(urllib.request.urlopen(base + "/api/state").read())
            self.assertEqual(len(st["agents"]), 3)
            self.assertIn("structures", st)
            st2 = json.loads(urllib.request.urlopen(base + f"/api/state?rev={st['rev']}").read())
            self.assertNotIn("structures", st2)
            ev = json.loads(urllib.request.urlopen(base + "/api/journal?kind=events").read())
            self.assertTrue(ev)
            html = urllib.request.urlopen(base + "/").read()
            self.assertIn(b"Olympus World", html)
            req = urllib.request.Request(base + "/api/pause", data=b"", method="POST")
            with self.assertRaises(urllib.error.HTTPError):   # other websites can't pause your world
                urllib.request.urlopen(req)
            req = urllib.request.Request(base + "/api/pause", data=b"", method="POST", headers={"X-Olympus": "1"})
            self.assertTrue(json.loads(urllib.request.urlopen(req).read())["paused"])
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(base + "/../config/secrets.env")
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()


class TestUpgrades(Base):
    def test_new_part_fields(self):
        p = clean_part({"shape": "arch", "rot": 450, "color": "FFAA00", "glow": "yes", "w": 0.05})
        self.assertEqual(p["shape"], "arch")
        self.assertEqual(p["rot"], 90.0)
        self.assertEqual(p["color"], "#ffaa00")
        self.assertTrue(p["glow"])
        self.assertEqual(p["w"], 0.1)
        q = clean_part({"color": "red; drop table", "glow": False})
        self.assertNotIn("color", q)
        self.assertNotIn("glow", q)
        self.assertNotIn("rot", q)

    def test_design_expands_with_offset_scale_and_rotation(self):
        designs = {"lamp": {"name": "Lamp", "parts": [
            {"shape": "box", "material": "iron", "dx": 1, "y": 0, "dz": 0, "w": 1, "h": 2, "d": 1}]}}
        parts, used, unknown = expand_parts(
            [{"design": "lamp", "dx": 5, "dz": 5, "scale": 2, "rot": 90}, {"design": "nope"}], designs, 20)
        self.assertEqual(used, ["Lamp"])
        self.assertEqual(unknown, ["nope"])
        p = parts[0]
        self.assertAlmostEqual(p["dx"], 5.0, places=1)   # (1*2) rotated 90 deg lands on -z
        self.assertAlmostEqual(p["dz"], 3.0, places=1)
        self.assertEqual(p["h"], 4)
        self.assertEqual(p["rot"], 90)

    def test_invent_then_anyone_builds_it(self):
        w = self.world()
        zeus, athena = w.state["agents"]["zeus"], w.state["agents"]["athena"]
        r = w.save_design(zeus, "a lamp", {"name": "Lamp Post", "description": "light",
                                           "parts": [{"shape": "cylinder", "h": 3}, {"shape": "sphere", "y": 3, "glow": True}]})
        self.assertIn("invented", r)
        athena["x"], athena["z"] = 0, 0
        r = w.apply_action("athena", {"action": "build", "name": "Lit Path", "x": 1, "z": 1,
                                      "parts": [{"design": "lamp post", "dx": 0}, {"design": "Lamp Post", "dx": 3}]})
        self.assertIn("using", r)
        self.assertEqual(len(w.find_structure("Lit Path")["parts"]), 4)
        self.assertEqual(w.state["designs"]["lamp post"]["uses"], 2)
        # someone else's invention of the same name doesn't overwrite Zeus's
        w.save_design(athena, "x", {"name": "Lamp Post", "parts": [{"shape": "box"}]})
        self.assertEqual(w.state["designs"]["lamp post"]["inventor"], "zeus")
        self.assertIn("lamp post (athena's)", w.state["designs"])

    def test_design_part_limit(self):
        w = self.world()
        w.save_design(w.state["agents"]["zeus"], "big", {"name": "Big", "parts": [{"shape": "box"}] * 100})
        self.assertEqual(len(w.state["designs"]["big"]["parts"]), 40)

    def test_shape_world_and_cooldown(self):
        w = self.world()
        r = w.apply_action("zeus", {"action": "shape_world", "weather": "storm", "sky": "#223344",
                                    "fog": 5, "reason": "I like storms"})
        env = w.state["environment"]
        self.assertEqual(env["weather"], "storm")
        self.assertEqual(env["sky"], "#223344")
        self.assertEqual(env["fog"], 1)
        self.assertEqual(env["by"], "zeus")
        r = w.apply_action("athena", {"action": "shape_world", "weather": "clear"})
        self.assertIn("settle", r)
        self.assertEqual(env["weather"], "storm")
        w.state["game_minutes"] += 400
        w.apply_action("athena", {"action": "shape_world", "weather": "clear", "sky": "not a colour"})
        self.assertEqual(env["weather"], "clear")
        self.assertEqual(env["sky"], "#223344")

    def test_old_world_file_upgrades(self):
        w = self.world()
        del w.state["designs"]
        del w.state["environment"]
        w.save()
        w2 = self.world()
        self.assertEqual(w2.state["designs"], {})
        self.assertEqual(w2.state["environment"]["weather"], "clear")
        self.assertIn("environment", w2.public_state())

    def test_prompt_shows_look_and_inventions(self):
        w = self.world()
        w.save_design(w.state["agents"]["zeus"], "lamp", {"name": "Lamp Post", "description": "a light", "parts": [{"shape": "box"}]})
        p = build_action_prompt(w, "athena")
        self.assertIn("WORLD LOOK: weather clear", p)
        self.assertIn('"Lamp Post" by Zeus', p)
        self.assertIn('"action":"invent"', p)
        self.assertIn('"action":"shape_world"', p)


class TestShutdownGuard(Base):
    def test_shutdown_needs_installer_header(self):
        app = App(self.dir, self.settings, fake=True, search_fn=fake_search)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/api/shutdown", data=b"", method="POST")
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(req)
            self.assertEqual(cm.exception.code, 403)
        finally:
            srv.shutdown()
            srv.server_close()


class TestUnstuck(Base):
    """1.3.0: a god saved mid-thought is freed; finished places; nudges when a god repeats itself."""

    def engine(self, w, brain=None):
        ledger = brains.UsageLedger(os.path.join(self.dir, "usage.json"))
        return Engine(w, brains.Router(brain or brains.FakeBrain(3), ledger), self.settings, search_fn=fake_search)

    def test_god_saved_mid_thought_is_freed_on_load(self):
        w = self.world()
        w.state["agents"]["zeus"]["status"] = "thinking"
        w.state["agents"]["athena"]["status"] = "reading"
        w.save()
        w2 = self.world()
        self.assertEqual(w2.state["agents"]["zeus"]["status"], "idle")
        self.assertEqual(w2.state["agents"]["athena"]["status"], "idle")
        self.assertFalse(w2.is_busy(w2.state["agents"]["zeus"]))

    def test_scheduler_frees_a_stuck_thinker(self):
        w = self.world()
        e = self.engine(w)
        for a in w.state["agents"].values():
            a["status"] = "thinking"
        self.assertIsNotNone(e.pick_agent())
        self.assertTrue(all(a["status"] == "idle" for a in w.state["agents"].values()))

    def test_place_is_finished_at_the_limit(self):
        from olympus_world.world import MAX_PARTS_PER_PLACE
        w = self.world()
        z = w.state["agents"]["zeus"]
        part = {"shape": "box", "w": 1, "h": 1, "d": 1}
        for _ in range(MAX_PARTS_PER_PLACE // MAX_PARTS_PER_BUILD + 2):
            w.apply_action("zeus", {"action": "build", "name": "Temple", "x": z["x"] + 1, "z": z["z"] + 1,
                                    "parts": [dict(part) for _ in range(MAX_PARTS_PER_BUILD)]})
        s = w.find_structure("Temple")
        self.assertEqual(len(s["parts"]), MAX_PARTS_PER_PLACE)
        self.assertTrue(s["finished"])
        r = w.apply_action("zeus", {"action": "build", "name": "Temple", "parts": [part]})
        self.assertIn("finished", r)
        self.assertEqual(len(s["parts"]), MAX_PARTS_PER_PLACE)
        self.assertIn("FINISHED", build_action_prompt(w, "hephaestus"))

    def test_oversized_old_place_is_finished_on_load(self):
        w = self.world()
        w.state["structures"]["x1"] = {"id": "x1", "name": "Huge", "purpose": "", "builder": "zeus", "x": 5, "z": 5,
                                       "parts": [{"shape": "box"}] * 380, "contributors": ["zeus"]}
        w.save()
        self.assertTrue(self.world().find_structure("Huge")["finished"])

    def test_repeating_god_is_told_it_is_stuck(self):
        w = self.world()
        a = w.state["agents"]["zeus"]
        a["habits"] = ["move:hephaestus"] * 7 + ["say:athena"]
        p = build_action_prompt(w, "zeus")
        self.assertIn("YOU ARE STUCK", p)
        self.assertIn("move hephaestus", p)
        a["habits"] = ["move:1,2", "wander:", "move:3,3", "move:0,0", "wander:", "move:2,2", "say:x", "move:9,9"]
        self.assertIn("just walking", build_action_prompt(w, "zeus"))

    def test_stale_goal_is_flagged(self):
        w = self.world()
        a = w.state["agents"]["athena"]
        a["goal"], a["goal_since"] = "polish the carving", 1
        w.state["game_minutes"] = 1440 * 5
        self.assertIn("same goal since day 1", build_action_prompt(w, "athena"))

    def test_decisions_are_recorded_as_habits(self):
        w = self.world()
        e = self.engine(w)
        for _ in range(10):
            e.run_once()
        total = sum(len(a["habits"]) for a in w.state["agents"].values())
        self.assertGreater(total, 0)
        self.assertTrue(all(len(a["habits"]) <= 12 for a in w.state["agents"].values()))

    def test_reflection_sees_places_and_asks_for_variety(self):
        seen = {}

        class Spy(brains.FakeBrain):
            def chat(self, system, user):
                if "TASK: reflect" in user:
                    seen["user"] = user
                return super().chat(system, user)
        w = self.world()
        z = w.state["agents"]["zeus"]
        w.apply_action("zeus", {"action": "build", "name": "Altar", "x": z["x"] + 1, "z": z["z"] + 1,
                                "parts": [{"shape": "box"}]})
        e = self.engine(w, Spy(2))
        e.reflect("zeus")
        self.assertIn('"Altar"', seen["user"])
        self.assertIn("Olympus needs variety", seen["user"])
        self.assertEqual(w.state["agents"]["zeus"]["habits"], [])
