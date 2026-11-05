"""Settings and secrets loading. Standard library only."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")
SECRETS_PATH = os.path.join(CONFIG_DIR, "secrets.env")
DEFAULT_DATA_DIR = os.path.join(ROOT, "data")
WEB_DIR = os.path.join(ROOT, "web")

DEFAULTS = {
    "port": 8788,
    "ollama_url": "http://127.0.0.1:11434",
    "local_model": "qwen2.5:7b",
    "gemini_model": "gemini-2.5-flash-lite",
    "gemini_daily_cap": 20,
    "web_daily_cap": 30,
    "think_pause_seconds": 3,
    "real_minutes_per_game_day": 60,
    "world_half_size": 40,
}


def load_settings(path=SETTINGS_PATH):
    settings = dict(DEFAULTS)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
        for k, v in user.items():
            if not k.startswith("_"):
                settings[k] = v
    return settings


def load_secrets(path=SECRETS_PATH):
    """Read KEY=VALUE lines. Environment variables win over the file."""
    secrets = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                secrets[k.strip()] = v.strip()
    for k in ("GEMINI_API_KEY",):
        if os.environ.get(k):
            secrets[k] = os.environ[k]
    return secrets


def save_secret(name, value, path=SECRETS_PATH):
    existing = {}
    if os.path.exists(path):
        existing = load_secrets(path)
    existing[name] = value
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Private keys for Olympus World. Never share or upload this file.\n")
        for k, v in existing.items():
            f.write(f"{k}={v}\n")
