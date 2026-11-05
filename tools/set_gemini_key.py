"""Save your Gemini API key on THIS PC only (config/secrets.env), then test it once.

Your typing is hidden. The key is never shown, printed or sent anywhere except Google.
"""
import getpass
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from olympus_world.brains import BrainError, GeminiBrain, extract_json  # noqa: E402
from olympus_world.config import load_settings, save_secret  # noqa: E402


def main():
    s = load_settings()
    print("Paste your Gemini API key and press Enter.")
    print("(Nothing will appear while you paste - that's normal. Right-click pastes in this window.)")
    key = getpass.getpass("Key: ").strip()
    if not key:
        print("No key entered. Nothing changed.")
        return 1
    print(f"Testing the key with {s['gemini_model']} (uses 1 Gemini request)...")
    try:
        out = extract_json(GeminiBrain(key, s["gemini_model"]).chat(
            "Reply with JSON only.", 'Reply exactly: {"ok": true}'))
    except BrainError as e:
        print(f"[FAIL] Google said: {e}")
        print("Key NOT saved. Check you copied the whole key, then try again.")
        return 1
    if not out.get("ok"):
        print("[FAIL] Unexpected reply. Key NOT saved.")
        return 1
    save_secret("GEMINI_API_KEY", key)
    print("[ OK ] Key works and is saved on this PC in config\\secrets.env")
    print(f"       Olympus will use at most {s['gemini_daily_cap']} Gemini requests per day.")
    return 0


if __name__ == "__main__":
    code = main()
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\nPress Enter to close this window.")
    except Exception:
        pass
    sys.exit(code)
