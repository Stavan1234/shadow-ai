import os
import sys
import time
import requests
import sounddevice as sd
import numpy as np
import webrtcvad
from openwakeword.model import Model
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

WAKE_MODE = os.getenv("SHADOW_WAKE_MODE", "openwakeword").lower()
WAKE_URL = "http://127.0.0.1:8090/wake"

def trigger_wake(is_vad=False):
    """Notify the orchestrator that the wake event was detected."""
    mode_str = "Voice activity (VAD)" if is_vad else "Wake word (openWakeWord)"
    print(f"[Wake] {mode_str} DETECTED! Sending trigger to orchestrator...")
    try:
        response = requests.post(WAKE_URL, json={"wake": True}, timeout=2.0)
        print(f"[Wake] Orchestrator response: {response.status_code}")
    except Exception as e:
        print(f"[Wake] Failed to notify orchestrator: {e}")

def run_openwakeword():
    print("==========================================================")
    print("        S.H.A.D.O.W. openWakeWord Listener Active        ")
    print("        Listening for: 'Hey Jarvis' (triggers Shadow)    ")
    print("==========================================================")
    
    try:
        oww = Model(wakeword_models=["hey_jarvis"])
    except Exception as e:
        print(f"[Error] Failed to load openwakeword model: {e}")
        sys.exit(1)
        
    def callback(indata, frames, time_info, status):
        if status:
            print(f"[Status] {status}", file=sys.stderr)
            
        try:
            audio_frame = indata[:, 0]
            prediction = oww.predict(audio_frame)
            if prediction.get("hey_jarvis", 0) > 0.5:
                trigger_wake(is_vad=False)
                time.sleep(1.0)
        except Exception as err:
            print(f"[Error in prediction] {err}", file=sys.stderr)

    try:
        with sd.InputStream(channels=1, samplerate=16000, blocksize=1280, dtype='int16', callback=callback):
            while True:
                sd.sleep(100)
    except KeyboardInterrupt:
        print("\n[Wake] Shutting down wake listener...")
    except Exception as e:
        print(f"[Error in audio stream] {e}", file=sys.stderr)

def run_vad():
    print("==========================================================")
    print("        S.H.A.D.O.W. Always-On VAD Listener Active        ")
    print("        Listening for voice trigger... (Say 'Hey Shadow') ")
    print("==========================================================")
    
    vad = webrtcvad.Vad(2)
    sample_rate = 16000
    frame_ms = 30
    frame_samples = int(sample_rate * frame_ms / 1000)
    speech_frames = 0
    
    def callback(indata, frames, time_info, status):
        nonlocal speech_frames
        if status:
            print(f"[Status] {status}", file=sys.stderr)
            
        try:
            audio_bytes = bytes(indata)
            is_speech = vad.is_speech(audio_bytes, sample_rate)
            if is_speech:
                speech_frames += 1
                if speech_frames >= 4:  # ~120ms of continuous speech
                    trigger_wake(is_vad=True)
                    speech_frames = 0
                    time.sleep(5.0)  # Sleep longer while orchestrator records and speaks
            else:
                speech_frames = max(0, speech_frames - 1)
        except Exception as err:
            print(f"[Error in VAD detection] {err}", file=sys.stderr)

    try:
        with sd.InputStream(channels=1, samplerate=16000, blocksize=frame_samples, dtype='int16', callback=callback):
            while True:
                sd.sleep(100)
    except KeyboardInterrupt:
        print("\n[Wake] Shutting down wake listener...")
    except Exception as e:
        print(f"[Error in audio stream] {e}", file=sys.stderr)

def main():
    if WAKE_MODE == "vad":
        run_vad()
    else:
        run_openwakeword()

if __name__ == "__main__":
    main()
