import os
import json
import time
from enum import Enum

class ShadowState(Enum):
    ASLEEP = "ASLEEP"          # Only wake-word listener active
    LISTENING = "LISTENING"    # Recording user speech
    PROCESSING = "PROCESSING"  # LLM/tools/memory running
    CONFIRMING = "CONFIRMING"  # Waiting for user yes/no confirmation
    SPEAKING = "SPEAKING"      # TTS reading response

_state = ShadowState.ASLEEP
_subscribers = []
STATUS_FILE = "data/status.json"

def get_state() -> ShadowState:
    global _state
    return _state

def set_state(new_state: ShadowState):
    global _state
    _state = new_state
    
    # Notify memory subscribers
    for callback in _subscribers:
        try:
            callback(new_state)
        except Exception:
            pass
            
    # Write to status.json for cross-process IPC
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "state": _state.value,
                "timestamp": time.time()
            }, f, indent=2)
    except Exception:
        pass

def subscribe(callback):
    """Register a callback for state changes."""
    if callback not in _subscribers:
        _subscribers.append(callback)
