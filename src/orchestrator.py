import os
import sys
import uuid
import asyncio
import uvicorn
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from logs.perf_logger import PerfLogger
from src.memory.conscious import ConsciousMemory
from src.state.machine import ShadowState, set_state
from src.stt.endpointing import record_until_silence
from src.stt.transcribe import transcribe
from src.tts.speak import speak, pre_render_fillers, play_random_filler
from src.lifecycle.sleep_wake import teardown_subsystems
from src.router.tiers import route

# Initialize FastAPI for wake trigger
app = FastAPI()
wake_event = asyncio.Event()

SLEEP_PHRASES = {"go to sleep shadow", "shadow go to sleep", "shadow sleep now"}

def check_sleep_command(transcript: str) -> bool:
    """Returns True if the transcript exactly matches a sleep command."""
    return transcript.strip().lower() in SLEEP_PHRASES

class WakePayload(BaseModel):
    wake: bool

@app.post("/wake")
async def trigger_wake(payload: WakePayload):
    """Wake-word listener calls this endpoint to wake the assistant."""
    if payload.wake:
        from src.state.machine import get_state
        if get_state() == ShadowState.ASLEEP:
            print("[Orchestrator] Wake event received from listener process.")
            wake_event.set()
            return {"status": "wake_triggered"}
        else:
            print(f"[Orchestrator] Wake event ignored. Current state is: {get_state().value}")
            return {"status": "ignored_busy"}
    return {"status": "ignored"}

async def start_wake_server():
    """Start local uvicorn HTTP server for IPC wake signals."""
    config = uvicorn.Config(
        app, 
        host="127.0.0.1", 
        port=8090, 
        log_level="warning",
        loop="asyncio"
    )
    server = uvicorn.Server(config)
    await server.serve()

async def run_voice_loop():
    """Main voice command orchestrator loop."""
    perf = PerfLogger()
    conscious = ConsciousMemory()
    
    # Pre-render filler phrases once at startup
    pre_render_fillers()
    
    print("\n" + "=" * 60)
    print("           S.H.A.D.O.W. LIVE VOICE ECHO LOOP ACTIVE           ")
    print("      Listening on port 8090 for wake triggers...            ")
    print("=" * 60 + "\n")
    
    while True:
        try:
            # 1. State: ASLEEP
            set_state(ShadowState.ASLEEP)
            is_vad_mode = os.getenv("SHADOW_WAKE_MODE", "openwakeword").lower() == "vad"
            prompt_word = "Hey Shadow" if is_vad_mode else "Hey Jarvis"
            print(f"[Shadow] Sleeping... waiting for wake word '{prompt_word}'...")
            
            # Await HTTP trigger event
            await wake_event.wait()
            wake_event.clear()
            
            # Start profiling session
            session_id = str(uuid.uuid4())[:8]
            perf.mark("wake_word_detected")
            print(f"\n--- Starting vocal session {session_id} ---")
            
            # 2. State: LISTENING
            set_state(ShadowState.LISTENING)
            
            # Speak greeting (blocks main thread until speech completes)
            speak("Yes, Sir?")
            
            # Record user speech (blocks until silence or timeout)
            perf.mark("stt_record_start")
            audio_file = await asyncio.to_thread(record_until_silence, "data/temp_input.wav")
            perf.mark("stt_record_end")
            
            # 3. State: PROCESSING
            set_state(ShadowState.PROCESSING)
            play_random_filler()
            
            # Transcribe audio using faster-whisper on CPU
            perf.mark("stt_transcribe_start")
            transcript = await asyncio.to_thread(transcribe, audio_file)
            perf.mark("stt_transcribe_end")
            
            if not transcript:
                is_vad_mode = os.getenv("SHADOW_WAKE_MODE", "openwakeword").lower() == "vad"
                if is_vad_mode:
                    print("[Shadow] Silent trigger (no speech). Ignoring.")
                    set_state(ShadowState.ASLEEP)
                else:
                    print("[Shadow] No speech transcribed.")
                    set_state(ShadowState.SPEAKING)
                    await asyncio.to_thread(speak, "I couldn't hear you, Sir.")
                perf.mark("session_end")
                perf.flush(session_id)
                continue
                
            # If in VAD mode, check if the word "shadow" is present in the transcription
            is_vad_mode = os.getenv("SHADOW_WAKE_MODE", "openwakeword").lower() == "vad"
            if is_vad_mode and "shadow" not in transcript.lower():
                print(f"[Shadow] Ignored speech: '{transcript}' (does not contain 'shadow')")
                set_state(ShadowState.ASLEEP)
                perf.mark("session_end")
                perf.flush(session_id)
                continue
                
            print(f"[User Spoke] '{transcript}'")
            
            # Check for sleep command before routing/processing
            if check_sleep_command(transcript):
                print(f"[Shadow] Sleep command detected: '{transcript}'")
                set_state(ShadowState.SPEAKING)
                await asyncio.to_thread(speak, "Going to sleep, Sir.")
                await asyncio.to_thread(teardown_subsystems)
                set_state(ShadowState.ASLEEP)
                perf.mark("session_end")
                perf.flush(session_id)
                print(f"--- Completed vocal session {session_id} ---\n")
                # Cooldown to let audio echo decay and clear any queued signals
                await asyncio.sleep(1.0)
                wake_event.clear()
                continue
                
            # Run the deterministic router
            perf.mark("route_start")
            tier_name = route(transcript)
            perf.mark("route_end")
            print(f"[Router] Routed transcript to {tier_name}")

            conscious.add_turn("user", transcript)
            
            # 4. State: SPEAKING
            set_state(ShadowState.SPEAKING)
            reply = f"Routing to {tier_name}. You said: {transcript}."
            conscious.add_turn("assistant", reply)
            
            # Speak the verbatim echo response
            perf.mark("tts_speak_start")
            await asyncio.to_thread(speak, reply)
            perf.mark("tts_speak_end")
            
            # 5. Flush session analytics
            perf.mark("session_end")
            perf.flush(session_id)
            print(f"--- Completed vocal session {session_id} ---\n")
            
            # Post-session cooldown: sleep to let echo decay, then clear false triggers
            await asyncio.sleep(1.0)
            wake_event.clear()
            
        except Exception as e:
            print(f"[Error in loop] {e}")
            await asyncio.sleep(2.0)

async def main():
    # Run the uvicorn wake receiver server and the main voice orchestrator loop concurrently
    await asyncio.gather(
        start_wake_server(),
        run_voice_loop()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Orchestrator] Shutting down voice assistant...")
