"""Setup check: runs the offline tests, then checks your local AI (Ollama).

Safe to run any time. It never changes your world.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from olympus_world.config import load_secrets, load_settings  # noqa: E402

OK, BAD = "[ OK ]", "[FAIL]"


def main():
    print("=" * 60)
    print(" Olympus World - setup check")
    print("=" * 60)
    if sys.version_info < (3, 9):
        print(f"{BAD} Python {sys.version.split()[0]} is too old. Need 3.9 or newer.")
        return 1
    print(f"{OK} Python {sys.version.split()[0]}")

    print("\nStep 1 of 3: offline tests (no AI, no internet)...")
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                       cwd=ROOT, capture_output=True, text=True)
    last = (r.stderr.strip().splitlines() or ["?"])
    if r.returncode != 0:
        print(r.stderr[-3000:])
        print(f"{BAD} Tests failed. Copy the text above and send it to Claude.")
        return 1
    ran = [l for l in last if l.startswith("Ran ")]
    print(f"{OK} {ran[0] if ran else 'tests passed'} - all passed")

    s = load_settings()
    print(f"\nStep 2 of 3: is Ollama running with {s['local_model']}?")
    try:
        with urllib.request.urlopen(s["ollama_url"].rstrip("/") + "/api/tags", timeout=10) as resp:
            tags = json.loads(resp.read())
    except Exception as e:
        print(f"{BAD} Can't reach Ollama at {s['ollama_url']} ({e}).")
        print("       Open the Ollama app (llama icon) so it runs in the system tray, then run this again.")
        return 1
    names = [m.get("name") for m in tags.get("models", [])]
    if s["local_model"] not in names:
        print(f"{BAD} Ollama is running but doesn't have {s['local_model']}.")
        print("       Models you have: " + (", ".join(names) or "none"))
        return 1
    print(f"{OK} Ollama is running and has {s['local_model']}")

    print("\nStep 3 of 3: one real thought from Zeus (takes 10-60 seconds)...")
    from olympus_world.brains import BrainError, OllamaBrain, Router, UsageLedger
    from olympus_world.mind import build_action_prompt, system_for
    from olympus_world.world import World
    tmp = tempfile.mkdtemp()
    w = World(tmp, s)
    router = Router(OllamaBrain(s["ollama_url"], s["local_model"]), UsageLedger(os.path.join(tmp, "u.json")))
    t0 = time.time()
    try:
        act = router.think(system_for(w.state["agents"]["zeus"]), build_action_prompt(w, "zeus"))
    except BrainError as e:
        print(f"{BAD} Zeus couldn't think: {e}")
        return 1
    print(f"{OK} Zeus answered in {time.time() - t0:.0f} seconds:")
    print(f"       thought: {act.get('thought', '')}")
    print(f"       action : {act.get('action', '')}")
    print(f"       goal   : {act.get('goal', '')}")

    gem = "set" if load_secrets().get("GEMINI_API_KEY") else "not set yet (optional)"
    print(f"\nGemini key for big moments: {gem}")
    print("\nALL CHECKS PASSED. You can start the world.")
    return 0


if __name__ == "__main__":
    code = main()
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\nPress Enter to close this window.")
    except Exception:
        pass
    sys.exit(code)
