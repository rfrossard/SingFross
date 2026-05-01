"""Persistent configuration — saved as JSON in the project root.
Secrets (USDB credentials) are read from .env and take priority over config.json.
"""
import json, os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PATH = os.path.join(_ROOT, "config.json")
_ENV  = os.path.join(_ROOT, ".env")


def _load_env() -> dict:
    """Parse a simple KEY=VALUE .env file. No dependency on python-dotenv."""
    env: dict = {}
    try:
        with open(_ENV) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env


_ENV_VARS = _load_env()

_DEFAULTS: dict = {
    "audio": {
        "volume": 0.8,
        "sync_offset_ms": 0,        # positive = lyrics appear earlier
    },
    "lyrics": {
        "font_slot":    "body_bold",
        "size":          36,
        "color":        [255, 255, 255],
        "active_color": [255, 196,  28],
        "sung_color":   [105, 105, 120],
    },
    "players": [
        {
            "name":   "Player 1",
            "avatar": "🎤",
            "color":  [255, 196,  28],
            "mic_device": None,         # None = default device
            "mic_sensitivity": 1.0,
        },
        {
            "name":   "Player 2",
            "avatar": "⭐",
            "color":  [ 56, 160, 255],
            "mic_device": None,
            "mic_sensitivity": 1.0,
        },
    ],
    "two_player": False,
    "usdb": {
        "username": "",
        "password": "",
    },
    "songs_dir": "songs",
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class Config:
    """Thread-safe, persistent configuration store."""

    def __init__(self):
        self._data: dict = {}
        self.load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def load(self):
        try:
            with open(_PATH, "r") as f:
                saved = json.load(f)
            self._data = _deep_merge(_DEFAULTS, saved)
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = dict(_DEFAULTS)

    def save(self):
        try:
            with open(_PATH, "w") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            print(f"[Config] Save failed: {e}")

    # ── Accessors ────────────────────────────────────────────────────────────

    def get(self, *keys, default=None):
        node = self._data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def set(self, *keys_and_value):
        """config.set("audio", "volume", 0.5)"""
        *keys, value = keys_and_value
        node = self._data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value

    # ── Convenience properties ───────────────────────────────────────────────

    @property
    def volume(self) -> float:
        return float(self.get("audio", "volume", default=0.8))

    @property
    def sync_offset_sec(self) -> float:
        return self.get("audio", "sync_offset_ms", default=0) / 1000.0

    @property
    def lyrics(self) -> dict:
        return self._data.get("lyrics", _DEFAULTS["lyrics"])

    @property
    def player(self) -> list:
        return self._data.get("players", _DEFAULTS["players"])

    @property
    def two_player(self) -> bool:
        return bool(self._data.get("two_player", False))

    @property
    def usdb_credentials(self) -> tuple[str, str]:
        # .env takes priority over config.json
        user = _ENV_VARS.get("USDB_USER") or self._data.get("usdb", {}).get("username", "")
        pw   = _ENV_VARS.get("USDB_PASS") or self._data.get("usdb", {}).get("password", "")
        return user, pw

    @property
    def songs_dir(self) -> str:
        d = self._data.get("songs_dir", "songs")
        return os.path.join(os.path.dirname(__file__), "..", d)


# Singleton
_instance: Config | None = None

def get() -> Config:
    global _instance
    if _instance is None:
        _instance = Config()
    return _instance
