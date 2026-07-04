import os
import sys
import subprocess
import winsound
from pathlib import Path

# Paths to binaries and models
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PIPER_EXE = PROJECT_ROOT / "bin" / "piper" / "piper" / "piper.exe"
PIPER_MODEL = PROJECT_ROOT / "models" / "en_US-lessac-medium.onnx"
OUTPUT_WAV = PROJECT_ROOT / "logs" / "out.wav"

def speak(text: str) -> bool:
    """
    Synthesizes the given text to speech using the local Piper binary
    and plays it back natively on Windows using winsound.
    """
    if not text.strip():
        return False
        
    print(f"[TTS] Synthesizing: '{text}'")
    
    # Ensure logs directory exists
    os.makedirs(OUTPUT_WAV.parent, exist_ok=True)
    
    # Command to run Piper
    cmd = [
        str(PIPER_EXE),
        "--model", str(PIPER_MODEL),
        "--length_scale", "1.15",
        "--output_file", str(OUTPUT_WAV)
    ]
    
    try:
        # Run Piper process silently
        # We pass text via standard input stream
        result = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            check=True
        )
        
        # Play the generated WAV file using winsound (blocking playback)
        if OUTPUT_WAV.exists():
            winsound.PlaySound(str(OUTPUT_WAV), winsound.SND_FILENAME)
            return True
        else:
            print("[TTS Error] Output wav file was not generated.")
            return False
            
    except subprocess.CalledProcessError as err:
        print(f"[TTS Error] Piper execution failed: {err.stderr.decode('utf-8', errors='ignore')}")
        return False
    except Exception as exc:
        print(f"[TTS Error] Failed to play or synthesize audio: {exc}")
        return False

FILLERS = [
    "Just a moment, Sir.",
    "Working on it.",
    "One second.",
    "Let me check."
]

def pre_render_fillers():
    """Pre-synthesizes filler phrases once at startup if they do not exist for the current voice model."""
    filler_dir = PROJECT_ROOT / "data" / "fillers"
    os.makedirs(filler_dir, exist_ok=True)
    model_name = PIPER_MODEL.stem
    
    for i, phrase in enumerate(FILLERS):
        out_path = filler_dir / f"filler_{model_name}_{i}.wav"
        if out_path.exists():
            continue
            
        print(f"[TTS] Pre-rendering filler: '{phrase}' -> {out_path.name}")
        cmd = [
            str(PIPER_EXE),
            "--model", str(PIPER_MODEL),
            "--length_scale", "1.15",
            "--output_file", str(out_path)
        ]
        try:
            subprocess.run(
                cmd,
                input=phrase.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                check=True
            )
        except Exception as e:
            print(f"[TTS Error] Failed to pre-render '{phrase}': {e}")

def play_random_filler() -> bool:
    """Plays a random pre-rendered filler WAV asynchronously matching the current voice model."""
    import random
    filler_dir = PROJECT_ROOT / "data" / "fillers"
    model_name = PIPER_MODEL.stem
    i = random.randint(0, len(FILLERS) - 1)
    filler_path = filler_dir / f"filler_{model_name}_{i}.wav"
    
    if filler_path.exists():
        try:
            print(f"[TTS] Playing filler: '{FILLERS[i]}'")
            winsound.PlaySound(str(filler_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return True
        except Exception as e:
            print(f"[TTS Error] Failed to play filler: {e}")
    return False

