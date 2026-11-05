"""Olympus World - an autonomous society of gods in a bare 3D world."""
import json as _json
import os as _os


def _read_version():
    try:
        path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "version.json")
        with open(path, "r", encoding="utf-8") as f:
            return str(_json.load(f)["version"])
    except Exception:
        return "0.0.0"


VERSION = _read_version()
