import os
import json
import time

MAX_TURNS = 10

class ConsciousMemory:
    def __init__(self, path="data/conscious_memory.json"):
        self.path = path
        self.turns = []
        self.last_session_summary = ""
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
                self.turns = d.get("turns", [])
                self.last_session_summary = d.get("last_session_summary", "")
        except FileNotFoundError:
            pass
        except Exception:
            pass

    def add_turn(self, role: str, text: str):
        """Append conversational turn and keep the buffer within limits."""
        self.turns.append({"role": role, "text": text, "t": time.time()})
        self.turns = self.turns[-MAX_TURNS * 2 :] # Keep last 10 full turns (20 roles: user & assistant)
        self._flush()

    def _flush(self):
        """Persist memory turns to local JSON file."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({
                    "turns": self.turns, 
                    "last_session_summary": self.last_session_summary
                }, f, indent=2)
        except Exception:
            pass
