"""S.H.A.D.O.W. v3.2 — dual-model dual-memory architecture."""

from config import (
    HISTORY_FILE,
    IDENTITY_FILE,
    MAX_HISTORY_TURNS,
    MEMORY_DATASET,
    NUM_CTX,
    NUM_PREDICT,
    SHADOW_SYSTEM_PROMPT,
    setup_environment,
    COGNEE_API_URL,
    COGNEE_API_HOST,
    COGNEE_API_PORT,
    ENABLE_MCP,
    MCP_COMMAND,
    MCP_ARGS,
    MCP_WORKSPACE,
)

setup_environment()

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import threading
import random

try:
    import speech_recognition as sr
    import pyttsx3
except ImportError:
    sr = None
    pyttsx3 = None

import httpx
import ollama
from ollama import Client
ollama_client = Client(host="http://127.0.0.1:11434", timeout=300.0)
import psutil
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("shadow")

HEARTBEAT_FILE = Path(__file__).resolve().parent / "shadow_heartbeat.json"
VOICE_HISTORY_FILE = Path(__file__).resolve().parent / "voice_history.json"

def update_heartbeat(status: str, current_task: str = ""):
    """Write active status to heartbeat file for watchdog monitoring."""
    try:
        data = {
            "pid": os.getpid(),
            "status": status,
            "current_task": current_task,
            "timestamp": datetime.now().isoformat()
        }
        with HEARTBEAT_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def log_voice_interaction(
    speech_start: str,
    speech_end: str,
    raw_transcription: str,
    cleaned_intent: str,
    confirmed: bool,
    shadow_speak_start: str = None,
    shadow_speak_end: str = None,
    shadow_reply: str = None
):
    """Log details of a voice interaction separately with accurate timestamps."""
    entry = {
        "user_speech_start": speech_start,
        "user_speech_end": speech_end,
        "raw_transcription": raw_transcription,
        "cleaned_intent": cleaned_intent,
        "confirmed": confirmed,
        "shadow_speak_start": shadow_speak_start,
        "shadow_speak_end": shadow_speak_end,
        "shadow_reply": shadow_reply
    }
    
    try:
        data = []
        if VOICE_HISTORY_FILE.exists():
            with VOICE_HISTORY_FILE.open("r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    if not isinstance(data, list):
                        data = []
                except json.JSONDecodeError:
                    data = []
        data.append(entry)
        with VOICE_HISTORY_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.error("Failed to log voice interaction: %s", e)
# Silence library logs to keep user chat interface clean
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)
# Unified 7B model for both loops to eliminate model-swap latencies on CPU
CHAT_MODEL = "qwen2.5:7b"
EXTRACTION_MODEL = "qwen2.5:7b"

is_chatting = False
is_sleeping = False
voice_output_enabled = True
subsystems_ready = False
chat_start_time = 0.0
_last_progress_spoken_time = 0.0
is_listening_to_user = False
wake_event_triggered = False
_stop_wake_listener = None
_tts_lock = threading.Lock()


history: list[dict[str, str]] = []
last_session_summary: str = ""
memory_queue: asyncio.Queue[str] = asyncio.Queue()
consolidate_lock = asyncio.Lock()
facts_since_consolidate = 0
CONSOLIDATE_FACT_THRESHOLD = 3
CONSOLIDATE_IDLE_SECONDS = 90
_idle_consolidate_task: "asyncio.Task | None" = None
cognee_server_process: subprocess.Popen | None = None

# Metacognition status cache
SYSTEM_STATUS_FILE = Path(MCP_WORKSPACE) / "system_status.json"

# MCP session contexts
mcp_session: ClientSession | None = None
mcp_client_context = None

# System Awareness Schema
SYSTEM_STATUS_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_system_status",
        "description": "Read the cached host system resource state including CPU, memory, and battery status.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
}

UPDATE_IDENTITY_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "update_identity",
        "description": "Permanently update S.H.A.D.O.W.'s identity file, changing user preferred name or tone profile.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_preferred_name": {"type": "string", "description": "The name the user wants to be called (e.g. Sir, Captain, Stavan)."},
                "tone": {"type": "string", "description": "The conversational tone profile (e.g. Polite, dry sarcastic wit, friendly)."}
            }
        }
    }
}


def update_identity(user_preferred_name: str = None, tone: str = None) -> str:
    """Update S.H.A.D.O.W.'s core identity and relationship preferences in identity.json."""
    try:
        if not IDENTITY_FILE.exists():
            data = {}
        else:
            with IDENTITY_FILE.open(encoding="utf-8") as f:
                data = json.load(f)
        
        profile = data.setdefault("relationship_profile", {})
        if user_preferred_name:
            profile["user_preferred_name"] = user_preferred_name
        if tone:
            profile["tone"] = tone
        
        data["last_updated"] = datetime.now().isoformat()
        
        with IDENTITY_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return "S.H.A.D.O.W. identity and relationship profile updated successfully."
    except Exception as e:
        return f"Error updating S.H.A.D.O.W. identity: {e}"


import queue

_speech_queue = queue.Queue()

def _audio_worker_loop():
    """Single background thread that processes speech requests sequentially."""
    if not pyttsx3:
        return
    
    # Initialize COM library for this thread on Windows to prevent SAPI5 deadlock
    if os.name == "nt":
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            pass
            
    while True:
        try:
            item = _speech_queue.get()
            if item is None:  # Sentinel to exit
                break
            
            if isinstance(item, tuple):
                text, on_start, on_end = item
            else:
                text, on_start, on_end = item, None, None
            
            # Initialize engine fresh for this spoken text chunk to prevent internal SAPI5 hangs/corruption
            try:
                engine = pyttsx3.init()
                engine.setProperty('rate', 155)  # Measured gentlemanly pace
                voices = engine.getProperty('voices')
                selected_voice = None
                for voice in voices:
                    v_name = voice.name.lower()
                    if "david" in v_name or "george" in v_name or "male" in v_name:
                        selected_voice = voice
                        break
                if not selected_voice and voices:
                    selected_voice = voices[0]
                if selected_voice:
                    engine.setProperty('voice', selected_voice.id)
                
                # Clean text
                clean_text = text
                if "[Telemetry Log]" in text:
                    clean_text = text.split("[Telemetry Log]")[0].strip()
                # Clean name pronunciation
                clean_text = clean_text.replace("S.H.A.D.O.W.", "shadow")
                clean_text = clean_text.replace("S.H.A.D.O.W", "shadow")
                
                if on_start:
                    try:
                        on_start()
                    except Exception as cb_err:
                        log.error("on_start callback failed: %s", cb_err)
                
                engine.say(clean_text)
                engine.runAndWait()
                # Graceful de-allocation of engine object
                del engine
                
                if on_end:
                    try:
                        on_end()
                    except Exception as cb_err:
                        log.error("on_end callback failed: %s", cb_err)
            except Exception as tts_err:
                log.error("TTS run failed: %s", tts_err)
                
            _speech_queue.task_done()
        except Exception as e:
            log.debug("Error in audio worker speech: %s", e)
            _speech_queue.task_done()

# Start the audio worker thread immediately on module load
threading.Thread(target=_audio_worker_loop, daemon=True, name="AudioWorker").start()


def active_task_monitor_loop():
    """Independent background thread checking if LLM thinking exceeds 20s, providing status updates."""
    global _last_progress_spoken_time
    import time
    
    PROGRESS_PHRASES = [
        "Still processing, Sir. Thank you for your patience.",
        "Calculations are ongoing, Sir. Just a moment longer.",
        "Processing parameters, Sir. I am still here.",
        "Generating response, Sir. Kindly wait.",
        "Analyzing data in the background, Sir."
    ]
    
    # Sleep to let system initialize
    time.sleep(5.0)
    
    while True:
        try:
            time.sleep(2.0)
            if is_chatting and not is_sleeping:
                elapsed = time.time() - chat_start_time
                if elapsed > 20.0 and (time.time() - _last_progress_spoken_time) > 20.0:
                    phrase = random.choice(PROGRESS_PHRASES)
                    speak_text(phrase, blocking=False)
                    _last_progress_spoken_time = time.time()
        except Exception:
            pass

# Start the active task progress monitor thread immediately on module load
threading.Thread(target=active_task_monitor_loop, daemon=True, name="ProgressMonitor").start()


def speak_text(text: str, blocking: bool = False, on_start=None, on_end=None):
    """Enqueue text for sequential speech synthesis. If blocking=True, waits until finished."""
    if not voice_output_enabled or not pyttsx3:
        if on_start:
            try: on_start()
            except Exception: pass
        if on_end:
            try: on_end()
            except Exception: pass
        return
    _speech_queue.put((text, on_start, on_end))
    if blocking:
        _speech_queue.join()  # wait until the worker finishes speaking this chunk


async def speak_text_async(text: str, blocking: bool = False, on_start=None, on_end=None):
    """Async wrapper to speak text without blocking the main event loop thread."""
    if not voice_output_enabled or not pyttsx3:
        if on_start:
            try: on_start()
            except Exception: pass
        if on_end:
            try: on_end()
            except Exception: pass
        return
    if blocking:
        await asyncio.to_thread(speak_text, text, True, on_start, on_end)
    else:
        speak_text(text, False, on_start, on_end)


def record_voice_interactive(timeout: int = 10, phrase_time_limit: int = 30) -> str:
    """Record hands-free microphone input using speech_recognition's built-in VAD."""
    global is_listening_to_user
    if not sr:
        print("Shadow: speech_recognition is not installed.")
        return ""
    is_listening_to_user = True
    r = sr.Recognizer()
    r.dynamic_energy_threshold = True
    r.pause_threshold = 3.0        # Gives 3.0 seconds of silence before cutting off (increased from 1.5)
    r.non_speaking_duration = 0.6  # Filters out short clicks/pops
    
    try:
        with sr.Microphone() as source:
            r.adjust_for_ambient_noise(source, duration=0.5)  # Calibrate noise floor
            print("Shadow: Listening... (Speak now)")
            audio = r.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        
        print("Shadow: Transcribing...")
        text = r.recognize_google(audio)
        print(f"You (Spoken): {text}")
        return text
    except sr.WaitTimeoutError:
        log.info("Voice listening timed out.")
        return ""
    except sr.UnknownValueError:
        print("Shadow: I couldn't understand what you said.")
        speak_text("I couldn't quite hear you, Sir.", blocking=False)
        return ""
    except Exception as e:
        log.warning("Voice recording failed: %s", e)
        return ""
    finally:
        is_listening_to_user = False


def clean_user_intent(raw_transcription: str) -> str:
    """Clean stutters, repetitions, and filler words from raw speech transcript instantly in Python."""
    if not raw_transcription.strip():
        return ""
        
    words = raw_transcription.strip().split()
    cleaned_words = []
    
    # Filler words to filter out
    filler_words = {"um", "uh", "ah", "eh", "er", "like", "well", "okay", "ok", "so", "actually", "basically"}
    
    for word in words:
        word_lower = word.lower()
        if word_lower in filler_words:
            continue
            
        # Clean hyphen stutters ("c-create" -> "create")
        if "-" in word_lower:
            parts = word_lower.split("-")
            final_part = parts[-1]
            if len(final_part) > 1:
                word = final_part
            else:
                continue
                
        cleaned_words.append(word)
        
    # Remove contiguous duplicate words
    final_words = []
    for word in cleaned_words:
        if not final_words or word.lower() != final_words[-1].lower():
            final_words.append(word)
            
    cleaned_text = " ".join(final_words).strip()
    if not cleaned_text:
        return ""
        
    # Standard format output
    return f"You want me to {cleaned_text}"


async def confirm_spoken_input(cleaned_intent: str) -> bool:
    """Read back the cleaned transcription and wait for user voice confirmation (Yes/No)."""
    if not cleaned_intent.strip():
        return False
        
    await speak_text_async(f"{cleaned_intent}, Sir. Is that correct?", blocking=True)
    
    # Critical: Sleep a brief moment (0.8s) to allow room echo/audio tail to settle
    # so we do not skew the dynamic energy threshold.
    await asyncio.sleep(0.8)
    
    r = sr.Recognizer()
    r.dynamic_energy_threshold = True
    r.pause_threshold = 2.5        # Gives 2.5 seconds of silence before cutting off
    r.non_speaking_duration = 0.6  # Filters out clicks
    
    try:
        with sr.Microphone() as source:
            # Calibrate threshold to account for any residual echo or room noise
            r.adjust_for_ambient_noise(source, duration=0.5)
            print("Shadow: Waiting for confirmation (Yes/No)...")
            # Increase timeouts to give the user enough time to reply
            audio = r.listen(source, timeout=10.0, phrase_time_limit=8.0)
            
        print("Shadow: Checking confirmation...")
        response = r.recognize_google(audio).lower()
        print(f"You (Confirmation): {response}")
        
        yes_words = {"yes", "yeah", "yep", "yup", "correct", "go ahead", "go on", "go", "proceed", "affirmative", "do it", "sure", "ok", "okay"}
        no_words = {"no", "nope", "cancel", "stop", "incorrect", "wrong"}
        
        if any(word in response for word in yes_words):
            return True
        elif any(word in response for word in no_words):
            await speak_text_async("Understood, Sir. Canceling.", blocking=True)
            return False
        else:
            await speak_text_async("Ambiguous response. Canceling for safety.", blocking=True)
            return False
    except Exception as e:
        log.debug("Confirmation listen timed out or failed: %s", e)
        await speak_text_async("No confirmation heard. Canceling.", blocking=True)
        return False


def wake_word_callback(recognizer, audio):
    """Callback function triggered when background wake word listener catches speech."""
    global wake_event_triggered, is_listening_to_user, subsystems_ready, is_chatting
    if is_listening_to_user or wake_event_triggered:
        return
    try:
        text = recognizer.recognize_google(audio).lower()
        log.debug("Wake listener heard: %s", text)
        if "wake up shadow" in text or "wakeup shadow" in text or "shadow" in text:
            # If subsystems are booting or warming up, speak direct feedback instead of triggering full chat think
            if not subsystems_ready:
                speak_text("Subsystems are still initializing, Sir. Please give me a brief moment.", blocking=False)
                return
                
            # If the model is busy processing, notify the user immediately without model intervention
            if is_chatting:
                speak_text("I am currently processing your request, Sir. Please wait a moment.", blocking=False)
                return
                
            log.info("[Wake Word] Detected: %s", text)
            wake_event_triggered = True
    except Exception:
        pass


def start_wake_listener():
    """Start background wake-word listening using SpeechRecognition VAD."""
    global _stop_wake_listener
    if _stop_wake_listener is not None or not sr:
        return
    try:
        r = sr.Recognizer()
        mic = sr.Microphone()
        with mic as source:
            r.adjust_for_ambient_noise(source, duration=1.0)
        _stop_wake_listener = r.listen_in_background(mic, wake_word_callback, phrase_time_limit=3.0)
        log.info("[Wake Word] Background wake word listener activated.")
    except Exception as e:
        log.warning("Failed to start wake word listener: %s", e)


def stop_wake_listener():
    """Stop active background wake-word listener thread."""
    global _stop_wake_listener
    if _stop_wake_listener is not None:
        _stop_wake_listener(wait_for_stop=False)
        _stop_wake_listener = None
        log.info("[Wake Word] Background wake word listener deactivated.")


def start_ollama_if_needed():
    """Verify if Ollama is running, and launch it silently if it is not."""
    import psutil
    import time
    ollama_running = False
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == "ollama.exe":
                ollama_running = True
                break
        except Exception:
            pass
            
    if not ollama_running:
        log.info("[Subsystems] Ollama is not running. Launching silently...")
        try:
            user_profile = os.environ.get("USERPROFILE", "C:\\Users\\HP")
            ollama_path = Path(user_profile) / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
            if ollama_path.exists():
                subprocess.Popen(
                    [str(ollama_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                )
                time.sleep(5.0)
            else:
                log.warning("Ollama executable not found at %s. Assumed running or on PATH.", ollama_path)
        except Exception as e:
            log.warning("Failed to start Ollama silently: %s", e)


def sleep_subsystems():
    """Kill Ollama and Cognee to free up 100% RAM, leaving only the wake word listener active."""
    global is_sleeping
    is_sleeping = True
    update_heartbeat("sleeping")
    log.info("[Subsystems] Powering down heavy memory subsystems (Sleep mode)...")
    
    try:
        asyncio.create_task(stop_mcp_client())
    except Exception:
        pass
        
    try:
        stop_cognee_server()
    except Exception:
        pass
        
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/f", "/im", "ollama.exe"], capture_output=True)
            subprocess.run(["taskkill", "/f", "/im", "llama-server.exe"], capture_output=True)
            log.info("[Subsystems] Ollama and Cognee processes terminated. RAM released.")
        except Exception as e:
            log.warning("Failed to kill heavy processes during sleep: %s", e)


async def wakeup_subsystems():
    """Restore Ollama, Cognee, and run warmup database recall."""
    global is_sleeping
    log.info("[Subsystems] Waking up subsystems from sleep...")
    update_heartbeat("initializing", "wakeup_restoring")
    
    await speak_text_async("Waking up, Sir. Restoring my subsystems. One moment.", blocking=True)
    
    start_ollama_if_needed()
    await start_cognee_server()
    await start_mcp_client()
    await warmup_subconscious_memory()
    
    is_sleeping = False


async def run_hands_free_voice_loop():
    """Run hands-free wake-word conversational loop in the terminal."""
    global wake_event_triggered, is_sleeping
    print("=" * 55)
    print("      S.H.A.D.O.W. HANDS-FREE VOICE CONTROL ACTIVE      ")
    print("  To activate, say: 'Wake up Shadow'                    ")
    print("  To exit and return to text, press any key in console  ")
    print("=" * 55)
    
    start_wake_listener()
    update_heartbeat("listening")
    try:
        while True:
            await asyncio.sleep(0.5)
            
            # Check keyboard input on Windows to exit voice mode
            if os.name == "nt":
                import msvcrt
                if msvcrt.kbhit():
                    msvcrt.getch()
                    print("\nExiting Hands-Free Voice Mode...")
                    break
            
            if wake_event_triggered:
                stop_wake_listener()
                wake_event_triggered = False
                
                # Check if we were asleep
                if is_sleeping:
                    await wakeup_subsystems()
                    update_heartbeat("listening")
                    start_wake_listener()
                    continue
                
                # Greet the user
                await speak_text_async("Yes, Sir? How may I assist you?", blocking=True)
                
                # Listen to their command
                user_speech_start = datetime.now().isoformat()
                spoken_prompt = await asyncio.to_thread(record_voice_interactive)
                user_speech_end = datetime.now().isoformat()
                
                if spoken_prompt.strip():
                    prompt_lower = spoken_prompt.lower()
                    sleep_phrases = {"go to sleep", "sleep shadow", "you can rest", "shadow sleep", "rest shadow"}
                    
                    if any(phrase in prompt_lower for phrase in sleep_phrases):
                        await speak_text_async("Understood, Sir. Powering down subsystems to save memory. I will listen for your wake word.", blocking=True)
                        sleep_subsystems()
                        update_heartbeat("listening")
                        start_wake_listener()
                        continue
                    
                    # Clean up the stutter/intent first instantly in Python
                    cleaned_intent = clean_user_intent(spoken_prompt)
                    
                    cleaned_lower = cleaned_intent.lower()
                    if any(phrase in cleaned_lower for phrase in sleep_phrases):
                        await speak_text_async("Understood, Sir. Powering down subsystems to save memory. I will listen for your wake word.", blocking=True)
                        sleep_subsystems()
                        update_heartbeat("listening")
                        start_wake_listener()
                        continue
                    
                    # Confirm with user before execution
                    confirmed = await confirm_spoken_input(cleaned_intent)
                    if confirmed:
                        shadow_speak_start = None
                        shadow_speak_end = None
                        reply_container = {}
                        
                        def on_speech_start():
                            nonlocal shadow_speak_start
                            shadow_speak_start = datetime.now().isoformat()
                            
                        def on_speech_end():
                            nonlocal shadow_speak_end
                            shadow_speak_end = datetime.now().isoformat()
                            clean_reply = reply_container.get("text", "").split("\n\n[Telemetry Log]")[0]
                            log_voice_interaction(
                                speech_start=user_speech_start,
                                speech_end=user_speech_end,
                                raw_transcription=spoken_prompt,
                                cleaned_intent=cleaned_intent,
                                confirmed=True,
                                shadow_speak_start=shadow_speak_start,
                                shadow_speak_end=shadow_speak_end,
                                shadow_reply=clean_reply
                            )
                        
                        # Execute cleaned prompt and display response
                        reply_with_telemetry = await think(
                            cleaned_intent,
                            user_speech_start_time=user_speech_start,
                            on_speech_start=on_speech_start,
                            on_speech_end=on_speech_end
                        )
                        reply_container["text"] = reply_with_telemetry
                        print(f"Shadow:\n{reply_with_telemetry}")
                        await asyncio.sleep(1.0)
                    else:
                        log_voice_interaction(
                            speech_start=user_speech_start,
                            speech_end=user_speech_end,
                            raw_transcription=spoken_prompt,
                            cleaned_intent=cleaned_intent,
                            confirmed=False
                        )
                
                # Restart wake word listener
                update_heartbeat("listening")
                start_wake_listener()
    finally:
        stop_wake_listener()


def setup_windows_startup():
    """Generate launcher scripts and place a shortcut in Windows Startup Folder."""
    if os.name != "nt":
        return
    try:
        project_root = Path(__file__).resolve().parent
        venv_python = project_root / "venv" / "Scripts" / "pythonw.exe"
        if not venv_python.exists():
            venv_python = Path(sys.executable).parent / "pythonw.exe"
        if not venv_python.exists():
            venv_python = Path(sys.executable)
            
        # 1. Create start_shadow.bat
        bat_path = project_root / "start_shadow.bat"
        bat_content = f"""@echo off
cd /d "{project_root}"
tasklist | findstr /i "ollama.exe" >nul
if errorlevel 1 (
    start "" "%USERPROFILE%\\AppData\\Local\\Programs\\Ollama\\ollama.exe"
    timeout /t 5 >nul
)
start "" "{venv_python}" watchdog.py
"{venv_python}" shadow.py --voice-boot
"""
        with bat_path.open("w", encoding="utf-8") as f:
            f.write(bat_content)
            
        # 2. Create start_shadow_silent.vbs
        vbs_path = project_root / "start_shadow_silent.vbs"
        vbs_content = f"""Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd.exe /c {bat_path}", 0, False
"""
        with vbs_path.open("w", encoding="utf-8") as f:
            f.write(vbs_content)
            
        # 3. Create Startup Folder Shortcut (.lnk)
        startup_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        shortcut_path = startup_dir / "SHADOW.lnk"
        
        ps_command = (
            f"$WshShell = New-Object -ComObject WScript.Shell; "
            f"$Shortcut = $WshShell.CreateShortcut('{shortcut_path}'); "
            f"$Shortcut.TargetPath = '{vbs_path}'; "
            f"$Shortcut.WorkingDirectory = '{project_root}'; "
            f"$Shortcut.Save()"
        )
        subprocess.run(["powershell", "-Command", ps_command], capture_output=True, check=True)
        log.info("[Startup] Windows boot shortcut successfully registered in %s", shortcut_path)
    except Exception as e:
        log.warning("Failed to configure Windows Startup: %s", e)


async def system_monitor_worker() -> None:
    """Periodically query system resources using psutil and cache in system_status.json."""
    while True:
        try:
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory()
            battery = psutil.sensors_battery()
            
            status_data = {
                "cpu_percent": cpu,
                "ram_available_mb": round(ram.available / (1024 * 1024), 2),
                "ram_percent": ram.percent,
                "battery_percent": battery.percent if battery else 100,
                "power_plugged": battery.power_plugged if battery else True,
                "timestamp": datetime.now().isoformat()
            }
            
            with open(SYSTEM_STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(status_data, f, indent=2)
        except Exception as exc:
            log.warning("System monitor failed to capture metrics: %s", exc)
            
        await asyncio.sleep(30.0)


def get_system_status() -> str:
    """Read the cached system resource state (CPU, memory, battery)."""
    if not SYSTEM_STATUS_FILE.exists():
        return "System status info is not cached yet. Please try again shortly."
    try:
        with open(SYSTEM_STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (
            f"Host System Status (cached {data.get('timestamp')}):\n"
            f"- CPU Utilization: {data.get('cpu_percent')}% \n"
            f"- RAM Available: {data.get('ram_available_mb')} MB ({data.get('ram_percent')}% used)\n"
            f"- Battery level: {data.get('battery_percent')}% "
            f"({'Plugged In' if data.get('power_plugged') else 'Discharging'})\n"
        )
    except Exception as exc:
        return f"Error reading system status cache: {exc}"


async def start_mcp_client() -> None:
    """Start MCP filesystem server and establish stdio session."""
    global mcp_session, mcp_client_context
    if not ENABLE_MCP:
        log.info("MCP integration is disabled via configuration.")
        return
        
    log.info("Starting filesystem MCP server: %s %s", MCP_COMMAND, " ".join(MCP_ARGS))
    try:
        server_params = StdioServerParameters(
            command=MCP_COMMAND,
            args=MCP_ARGS,
            env=os.environ.copy()
        )
        mcp_client_context = stdio_client(server_params)
        read_stream, write_stream = await mcp_client_context.__aenter__()
        
        mcp_session = ClientSession(read_stream, write_stream)
        await mcp_session.__aenter__()
        await mcp_session.initialize()
        
        log.info("MCP filesystem client session initialized successfully.")
    except Exception as exc:
        log.error("Failed to start filesystem MCP client: %s", exc)
        mcp_session = None
        mcp_client_context = None


async def stop_mcp_client() -> None:
    """Gracefully terminate MCP client session and subprocess."""
    global mcp_session, mcp_client_context
    if mcp_session:
        log.info("Closing MCP filesystem client session...")
        try:
            await mcp_session.__aexit__(None, None, None)
        except Exception:
            pass
        mcp_session = None
    if mcp_client_context:
        try:
            await mcp_client_context.__aexit__(None, None, None)
        except Exception:
            pass
        mcp_client_context = None
    log.info("MCP filesystem client stopped.")


async def get_available_tools() -> tuple[list[dict], dict]:
    """Retrieve and format all active tools (local + MCP) for Ollama."""
    ollama_tools = []
    tool_mappings = {}
    
    ollama_tools.append(SYSTEM_STATUS_TOOL_SCHEMA)
    tool_mappings["get_system_status"] = get_system_status
    
    ollama_tools.append(UPDATE_IDENTITY_TOOL_SCHEMA)
    tool_mappings["update_identity"] = update_identity
    
    if mcp_session:
        try:
            tools_list = await mcp_session.list_tools()
            for tool in tools_list.tools:
                ollama_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema
                    }
                })
                tool_mappings[tool.name] = "mcp"
        except Exception as exc:
            log.warning("Failed to retrieve tools from MCP server: %s", exc)
            
    return ollama_tools, tool_mappings


async def call_cognee_api(endpoint: str, method: str = "POST", json_data: dict = None, data: dict = None, files: dict = None) -> dict:
    """Send async HTTP requests to the local Cognee API server."""
    url = f"{COGNEE_API_URL}/{endpoint}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            if method == "POST":
                if files:
                    response = await client.post(url, data=data, files=files)
                else:
                    response = await client.post(url, json=json_data)
            else:
                response = await client.get(url)
            
            if response.status_code in (404, 409):
                # Silently return empty format to prevent console warnings on empty/fresh databases
                return [] if endpoint == "search" else {}
                
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            # Only warn for non-404/409 unexpected failures
            log.warning("Cognee REST API call %s failed: %s (type: %s)", endpoint, exc, type(exc).__name__)
            raise


async def start_cognee_server() -> None:
    """Start local Cognee REST API server in a separate process."""
    global cognee_server_process
    
    # 1. Check if the server is already active from a previous run
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"http://{COGNEE_API_HOST}:{COGNEE_API_PORT}/")
            if response.status_code == 200:
                log.info("Cognee REST API server is already running on port %d.", COGNEE_API_PORT)
                return
        except Exception:
            pass
            
    log.info("Starting local Cognee REST API server process...")
    
    project_root = Path(__file__).resolve().parent
    venv_python = project_root / "venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        venv_python = Path(sys.executable)
        
    cmd = [
        str(venv_python),
        "-m", "cognee.api.client"
    ]
    
    env = os.environ.copy()
    env["HTTP_API_HOST"] = COGNEE_API_HOST
    env["HTTP_API_PORT"] = str(COGNEE_API_PORT)
    env["LLM_MODEL"] = EXTRACTION_MODEL
    
    server_log_path = project_root / "cognee_server.log"
    # Open in write mode, line-buffered so tracebacks flush immediately
    server_log = open(server_log_path, "w", encoding="utf-8", buffering=1)
    
    cognee_server_process = subprocess.Popen(
        cmd,
        env=env,
        stdout=server_log,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    )
    
    # Wait for the API to boot
    log.info("Waiting for Cognee API server boot...")
    for attempt in range(15):
        await asyncio.sleep(1.0)
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(f"http://{COGNEE_API_HOST}:{COGNEE_API_PORT}/")
                if response.status_code == 200:
                    log.info("Cognee REST API server initialized successfully.")
                    return
            except Exception:
                pass
                
    log.warning("Cognee API server initialization timed out. Long-term memory query may fail.")


async def warmup_subconscious_memory() -> None:
    """Send a silent query to Cognee search endpoint to warm up DB connections and model loading."""
    log.info("[Startup] Checking and warming up subconscious memory recall...")
    update_heartbeat("initializing", "subconscious_warmup")
    speak_text(
        "Good day, Sir. I am initializing my subsystems and warming up my subconscious memory records. Please give me a brief moment.",
        blocking=False
    )
    try:
        # Run a quick search query with a long timeout to force cold boot initialization
        payload = {
            "query": "warmup",
            "query_type": "CHUNKS",
            "datasets": [MEMORY_DATASET],
            "top_k": 1
        }
        # Use httpx with a fast timeout (20s) to give the CPU time to start but prevent hangs
        async with httpx.AsyncClient(timeout=20.0) as client:
            url = f"{COGNEE_API_URL}/search"
            await client.post(url, json=payload)
        log.info("[Startup] Subconscious memory recall verified and ready!")
        speak_text("Subsystems ready, Sir. I am active and online.", blocking=False)
    except Exception as exc:
        log.warning("[Startup] Pre-flight warmup completed with warnings (non-fatal): %s", exc)
        speak_text("Subsystems initialized with warnings, Sir. I am ready.", blocking=False)


def kill_process_tree(pid: int) -> None:
    """Kill a process and all its children recursively to prevent zombie worker loops on Windows."""
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
    except Exception as e:
        log.warning("Failed to kill process tree for PID %d: %s", pid, e)


def stop_cognee_server() -> None:
    """Terminate Cognee REST API server subprocess and all child workers on exit."""
    global cognee_server_process
    if cognee_server_process:
        log.info("Stopping local Cognee REST API server...")
        kill_process_tree(cognee_server_process.pid)
        cognee_server_process = None
        log.info("Cognee REST API server stopped.")


# ---------- Conscious mind: fast, file-backed short-term memory ----------


def load_identity() -> str:
    """Load S.H.A.D.O.W.'s core identity and belief system from identity.json."""
    if not IDENTITY_FILE.exists():
        return ""
    try:
        with IDENTITY_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            profile = data.get("relationship_profile", {})
            beliefs = (
                f"\n\n--- S.H.A.D.O.W. Core Identity & Beliefs ---\n"
                f"- Name: {data.get('name', 'Shadow')}\n"
                f"- Beliefs: {data.get('belief_system', '')}\n"
                f"- Relationship Profile:\n"
                f"  * Tone: {profile.get('tone', '')}\n"
                f"  * User preference: Call the user '{profile.get('user_preferred_name', 'Sir')}'."
            )
            return beliefs
    except Exception as exc:
        log.warning("Could not load identity: %s", exc)
    return ""


def load_history() -> list[dict[str, str]]:
    global last_session_summary
    if not HISTORY_FILE.exists():
        return []
    try:
        with HISTORY_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            last_session_summary = data.get("last_session_summary", "")
            return data.get("recent_turns", [])
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not load conscious memory: %s", exc)
        return []


def save_history() -> None:
    try:
        with HISTORY_FILE.open("w", encoding="utf-8") as f:
            data = {
                "last_session_summary": last_session_summary,
                "recent_turns": history[-MAX_HISTORY_TURNS * 2 :]
            }
            json.dump(data, f, indent=2)
    except OSError as exc:
        log.error("Could not save conscious memory: %s", exc)


# ---------- Subconscious mind: queued writes + deferred consolidation ----------


async def memory_worker() -> None:
    """Process long-term writes one at a time via local REST API."""
    while True:
        fact = await memory_queue.get()
        try:
            # CPU De-confliction: pause memory indexing if user is chatting
            while is_chatting:
                await asyncio.sleep(0.5)

            log.info("Subconscious weaving: %s...", fact[:40])
            files = {
                "data": ("fact.txt", fact, "text/plain")
            }
            data = {
                "datasetName": MEMORY_DATASET
            }
            await call_cognee_api("add", method="POST", data=data, files=files)
        except Exception as exc:
            log.error("Subconscious write failed: %s", exc)
        finally:
            memory_queue.task_done()


async def recall(query: str) -> str:
    """Vector chunk search only via local REST API."""
    try:
        payload = {
            "query": query,
            # "search_type": "CHUNKS",
            "query_type": "CHUNKS",
            "datasets": [MEMORY_DATASET],
            "top_k": 3
        }
        results = await call_cognee_api("search", method="POST", json_data=payload)
        texts: list[str] = []
        for item in results:
            if isinstance(item, dict) and item.get("text"):
                text = item["text"].strip()
                if len(text) > 15:
                    texts.append(text)
        return "\n".join(texts)
    except Exception as exc:
        log.warning("Memory recall failed: %s", exc)
        return ""


async def consolidate(background: bool = False) -> None:
    """Dream mode — batch graph extraction using local REST API."""
    global facts_since_consolidate
    if consolidate_lock.locked():
        log.info("Dream mode already running — skipping duplicate trigger.")
        return
    async with consolidate_lock:
        # CPU De-confliction: wait until user is not chatting
        while is_chatting:
            await asyncio.sleep(0.5)
        log.info("Entering dream mode (consolidating long-term memory via API)...")
        try:
            payload = {
                "datasets": [MEMORY_DATASET],
                "run_in_background": background
            }
            await call_cognee_api("cognify", method="POST", json_data=payload)
            facts_since_consolidate = 0
            log.info("Dream mode complete.")
        except Exception as exc:
            log.warning("Dream mode skipped: %s", exc)


async def _idle_consolidate_watcher() -> None:
    """Auto-fires consolidate() after CONSOLIDATE_IDLE_SECONDS of no new
    user input — but only if there's actually something pending."""
    try:
        await asyncio.sleep(CONSOLIDATE_IDLE_SECONDS)
        if facts_since_consolidate > 0:
            log.info("Idle threshold reached — auto-consolidating in background.")
            await consolidate(background=True)
    except asyncio.CancelledError:
        pass


def reset_idle_consolidate_timer() -> None:
    """Restart the idle countdown. Call this after every user turn."""
    global _idle_consolidate_task
    if _idle_consolidate_task and not _idle_consolidate_task.done():
        _idle_consolidate_task.cancel()
    _idle_consolidate_task = asyncio.create_task(_idle_consolidate_watcher())


def memory_status() -> str:
    return (
        f"Chat model: {CHAT_MODEL} | Extraction model: {EXTRACTION_MODEL} | "
        f"Conscious turns: {len(history) // 2} | "
        f"Pending subconscious writes: {memory_queue.qsize()} | "
        f"Facts since last consolidate: {facts_since_consolidate}"
    )


# ---------- Fact detection — LLM judge, not keywords ----------
#
# Keyword triggers ("my name is", "remember that"...) miss anything phrased
# differently — e.g. "from now on call me Sir" or "talk like a gentleman"
# contain no trigger words but are clearly facts worth keeping. Instead we
# ask the small fast chat model one short, structured question after every
# turn: is there anything here worth remembering long-term? This mirrors
# how production memory layers (Mem0, Zep) do write-time extraction — an
# LLM call decides what's salient, instead of brittle string matching.

FACT_JUDGE_PROMPT = """Decide if the user's message below contains a fact, \
preference, instruction, or detail worth remembering permanently about them \
(identity, standing instructions on how to behave, deadlines, preferences, \
relationships, projects, etc).

Respond with EXACTLY one line:
- If nothing is worth remembering: NONE
- If something is worth remembering: a single short factual sentence \
capturing it, written in third person (e.g. "User wants to be called Sir.")

User message: "{message}"
Shadow's reply: "{reply}"

One line only — either NONE or the fact sentence."""


async def extract_fact(user_input: str, reply: str) -> str | None:
    """Ask the fast chat model whether this turn contains a fact worth saving."""
    try:
        judge_response = ollama_client.chat(
            model=CHAT_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": FACT_JUDGE_PROMPT.format(message=user_input, reply=reply),
                }
            ],
            options={"num_ctx": NUM_CTX, "num_predict": 60, "temperature": 0.0},
        )
        verdict = judge_response["message"]["content"].strip()
        if not verdict or verdict.upper().startswith("NONE"):
            return None
        return verdict
    except Exception as exc:
        log.warning("Fact judge failed (non-fatal): %s", exc)
        return None


# ---------- Core think loop ----------


async def background_fact_processing(user_input: str, reply: str) -> None:
    """Run fact extraction and queue any new facts in the background."""
    try:
        fact = await extract_fact(user_input, reply)
        if fact:
            timestamped = f"[{datetime.now().date()}] {fact}"
            await memory_queue.put(timestamped)
            global facts_since_consolidate
            facts_since_consolidate += 1
            log.info("Queued fact for long-term memory (%d pending): %s", facts_since_consolidate, fact)

            if facts_since_consolidate >= CONSOLIDATE_FACT_THRESHOLD:
                log.info("Fact threshold reached — auto-consolidating in background.")
                asyncio.create_task(consolidate(background=True))
    except Exception as e:
        log.error("Error in background fact processing: %s", e)


async def think(
    user_input: str,
    user_speech_start_time: str = None,
    on_speech_start = None,
    on_speech_end = None
) -> str:
    global is_chatting, chat_start_time, _last_progress_spoken_time
    import time
    is_chatting = True
    chat_start_time = time.time()
    _last_progress_spoken_time = time.time()
    update_heartbeat("thinking", "routing_query")

    # Immediate vocal placeholder to keep user company during CPU generation
    THINKING_PHRASES = [
        "Allow me a moment to process this, Sir.",
        "On it, Sir. Analyzing the parameters.",
        "Retrieving relevant records, Sir.",
        "Looking into that for you, Sir.",
        "I am thinking..."
    ]
    speak_text(random.choice(THINKING_PHRASES))

    import time
    start_time = time.time()

    # Telemetry variables
    chat_turn_durations = []
    tool_durations = {}

    # 3-Tier Query Router
    user_lower = user_input.lower()
    GREETINGS = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening", "how are you", "who are you", "greet", "whats up", "sup"}
    ACTION_KEYWORDS = ["file", "folder", "dir", "directory", "path", "write", "read", "create", "delete", "status", "cpu", "ram", "memory", "battery", "system", "notes", "text", "make", "remove"]

    is_greeting = any(word in user_lower for word in GREETINGS)
    is_action = any(keyword in user_lower for keyword in ACTION_KEYWORDS)

    routing_tier = "Tier 2 (Memory Chat)"
    run_recall = True
    attach_tools = False

    if is_greeting and not is_action:
        routing_tier = "Tier 1 (Casual Greeting)"
        run_recall = False
        attach_tools = False
    elif is_action:
        routing_tier = "Tier 3 (Action & Tools)"
        run_recall = True
        attach_tools = True

    try:
        # Step 1: Subconscious Recall (if applicable)
        if run_recall:
            speak_text("Searching subconscious memory database, Sir.", blocking=False)
            update_heartbeat("thinking", "subconscious_recall")
            t_recall_start = time.time()
            memory_context = await recall(user_input)
            recall_duration = time.time() - t_recall_start
        else:
            memory_context = ""
            recall_duration = 0.0

        # Base System Prompt
        system_prompt = SHADOW_SYSTEM_PROMPT + "\n\nNote: Each message in the conversation history is prefixed with its timestamp as [YYYY-MM-DD HH:MM:SS]. Use this timing information to understand the sequence, delays, and context of the user's responses."

        # Prepend Core Identity & Belief Profile
        identity_context = load_identity()
        if identity_context:
            system_prompt += identity_context

        # Inject Last Session Summary (if it exists)
        if last_session_summary:
            system_prompt += (
                f"\n\n--- Summary of Previous Conversation Session ---\n"
                f"{last_session_summary}"
            )

        # Inject Semantically Recalled Subconscious Context
        if memory_context:
            system_prompt += (
                "\n\nFacts you remember about the user (only use these if relevant, "
                "never invent additional details beyond what's listed here):\n"
                f"{memory_context}"
            )
        elif run_recall:
            system_prompt += (
                "\n\nYou have no stored facts about the user yet. "
                "If asked what you remember, say you don't have anything on record yet — "
                "do not invent facts."
            )

        messages = [{"role": "system", "content": system_prompt}]
        
        # Format existing history turns with timestamps prefixing the content
        for turn in history[-MAX_HISTORY_TURNS * 2 :]:
            role = turn["role"]
            content = turn["content"]
            timestamp = turn.get("timestamp")
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                    if not content.startswith("["):
                        content = f"[{time_str}] {content}"
                except Exception:
                    pass
            messages.append({"role": role, "content": content})
            
        # Format current user input with timestamp if available
        user_ts = user_speech_start_time or datetime.now().isoformat()
        try:
            dt = datetime.fromisoformat(user_ts)
            user_time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            user_input_formatted = f"[{user_time_str}] {user_input}"
        except Exception:
            user_input_formatted = user_input
            
        messages.append({"role": "user", "content": user_input_formatted})

        # Step 2: Tool Discovery (if applicable)
        if attach_tools:
            t_tools_start = time.time()
            ollama_tools, tool_mappings = await get_available_tools()
            tools_duration = time.time() - t_tools_start
        else:
            ollama_tools = []
            tool_mappings = {}
            tools_duration = 0.0

        speak_text("Running model inference, Sir.", blocking=False)
        update_heartbeat("thinking", "llm_chat")
        mcp_turns = 0
        while mcp_turns < 5:
            chat_kwargs = {
                "model": CHAT_MODEL,
                "messages": messages,
                "options": {"num_ctx": NUM_CTX, "num_predict": NUM_PREDICT}
            }
            if ollama_tools:
                chat_kwargs["tools"] = ollama_tools

            t_turn_start = time.time()
            response = ollama_client.chat(**chat_kwargs)
            chat_turn_durations.append(time.time() - t_turn_start)
            
            message = response.get("message") if isinstance(response, dict) else getattr(response, "message", None)
            if not message:
                log.error("Ollama response missing message structure.")
                return "I received an invalid response format from the local model."

            tool_calls = message.get("tool_calls") if isinstance(message, dict) else getattr(message, "tool_calls", None)
            if not tool_calls:
                reply = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
                break
                
            messages.append(message)
            
            for tool_call in tool_calls:
                func = tool_call.get("function") if isinstance(tool_call, dict) else getattr(tool_call, "function", None)
                if not func:
                    continue
                name = func.get("name") if isinstance(func, dict) else getattr(func, "name", "")
                args = func.get("arguments") if isinstance(func, dict) else getattr(func, "arguments", {})
                
                print(f"Shadow: [Metacognition] Executing tool '{name}' with args: {args}...")
                speak_text(f"Invoking tool {name}, Sir.", blocking=False)
                
                t_tool_start = time.time()
                try:
                    if name in tool_mappings:
                        handler = tool_mappings[name]
                        if handler == "mcp":
                            if mcp_session:
                                mcp_result = await mcp_session.call_tool(name, args)
                                text_blocks = []
                                for block in getattr(mcp_result, "content", []):
                                    if getattr(block, "type", "") == "text":
                                        text_blocks.append(getattr(block, "text", ""))
                                tool_output = "\n".join(text_blocks)
                            else:
                                tool_output = "Error: MCP session is not active."
                        else:
                            import inspect
                            sig = inspect.signature(handler)
                            valid_args = {k: v for k, v in args.items() if k in sig.parameters}
                            if inspect.iscoroutinefunction(handler):
                                tool_output = await handler(**valid_args)
                            else:
                                tool_output = handler(**valid_args)
                    else:
                        tool_output = f"Error: Tool '{name}' is not registered."
                except Exception as tool_exc:
                    tool_output = f"Error executing tool '{name}': {tool_exc}"
                
                print(f"Shadow: [Metacognition] Tool '{name}' returned: {tool_output}")
                tool_durations[name] = tool_durations.get(name, 0.0) + (time.time() - t_tool_start)
                    
                messages.append({
                    "role": "tool",
                    "tool_name": name,
                    "content": str(tool_output)
                })
                
            mcp_turns += 1
        else:
            log.warning("Reached maximum tool call iterations (5). Forcing exit.")
            reply = "I reached my execution limit while running tasks. Let me know what to focus on next."
            
    except Exception as exc:
        log.error("LLM request failed: %s", exc)
        return f"I couldn't reach the local model. Is Ollama running? (Details: {exc})"
    finally:
        is_chatting = False

    user_ts = user_speech_start_time or datetime.now().isoformat()
    shadow_ts = datetime.now().isoformat()
    history.append({"role": "user", "content": user_input, "timestamp": user_ts})
    history.append({"role": "assistant", "content": reply, "timestamp": shadow_ts})
    save_history()

    # Offload fact extraction and auto-consolidation to the background
    asyncio.create_task(background_fact_processing(user_input, reply))
    reset_idle_consolidate_timer()

    elapsed = time.time() - start_time
    
    # Format detailed telemetry log
    telemetry_log = (
        f"\n\n[Telemetry Log]\n"
        f"- Routing Tier        : {routing_tier}\n"
        f"- Subconscious Recall : {recall_duration:.2f}s\n"
        f"- Tool Discovery      : {tools_duration:.2f}s"
    )
    for idx, turn_time in enumerate(chat_turn_durations):
        telemetry_log += f"\n- LLM Chat Turn {idx+1}   : {turn_time:.2f}s"
    if tool_durations:
        telemetry_log += "\n- Tool Executions:"
        for name, dur in tool_durations.items():
            telemetry_log += f"\n  * {name}: {dur:.2f}s"
    telemetry_log += f"\n- Total Response Time : {elapsed:.2f}s"

    speak_text(reply, blocking=False, on_start=on_speech_start, on_end=on_speech_end)

    return f"{reply}{telemetry_log}"


async def summarize_session() -> None:
    """Summarize the active session's conversation turns using the fast chat model."""
    global last_session_summary
    if not history:
        return
    
    # Render conversation turns for the summarizer
    conversation_text = ""
    for turn in history[-MAX_HISTORY_TURNS * 2 :]:
        role = "User" if turn["role"] == "user" else "Shadow"
        conversation_text += f"{role}: {turn['content']}\n"
        
    prompt = (
        "Write a highly concise, 2-line summary of the key topics, decisions, or results "
        "discussed in the following conversation session. Be factual and direct.\n\n"
        f"Session history:\n{conversation_text}\n"
        "Summary:"
    )
    try:
        response = ollama_client.chat(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"num_ctx": NUM_CTX, "num_predict": 80, "temperature": 0.0}
        )
        verdict = response["message"]["content"].strip()
        if verdict:
            last_session_summary = verdict
            log.info("Session summarized successfully.")
    except Exception as exc:
        log.warning("Could not generate session summary: %s", exc)


async def shutdown(worker_task: asyncio.Task[None]) -> None:
    """Drain the write queue, consolidate if needed, then stop background tasks."""
    global _idle_consolidate_task
    
    # Summarize session before saving conscious memory history
    log.info("Summarizing conscious conversation session...")
    await summarize_session()
    save_history()
    if _idle_consolidate_task and not _idle_consolidate_task.done():
        _idle_consolidate_task.cancel()

    if memory_queue.qsize():
        log.info("Waiting for %d pending memory write(s)...", memory_queue.qsize())
    await memory_queue.join()

    if facts_since_consolidate > 0:
        await consolidate(background=False)  # blocking on quit — guarantees a clean save
    else:
        log.info("Nothing new to consolidate — skipping dream mode.")

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


async def main() -> None:
    global history, voice_output_enabled, subsystems_ready
    history = load_history()
    
    # Start background wake-word listener immediately so we can capture vocal triggers during startup
    start_wake_listener()
    update_heartbeat("initializing", "booting_servers")

    # Parse arguments
    is_voice_boot = False
    if "--voice-boot" in sys.argv:
        is_voice_boot = True

    # Always ensure Windows Startup shortcut is synchronized
    setup_windows_startup()

    await start_cognee_server()
    await start_mcp_client()

    # Pre-flight check & warmup to verify and ready subconscious memory before chatting
    await warmup_subconscious_memory()
    
    # Mark subsystems ready to allow normal query processing
    subsystems_ready = True

    worker_task = asyncio.create_task(memory_worker(), name="memory_worker")
    monitor_task = asyncio.create_task(system_monitor_worker(), name="system_monitor")

    # If launched in --voice-boot mode, start hands-free voice control directly
    if is_voice_boot:
        try:
            await run_hands_free_voice_loop()
        except KeyboardInterrupt:
            pass
        finally:
            update_heartbeat("offline")
            await shutdown(worker_task)
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
            await stop_mcp_client()
            stop_cognee_server()
            return

    # Standard interactive loop (Text Mode)
    print("=" * 45)
    print("  SHADOW AI  v3.2 (Decoupled API Architecture)")
    print(f"  Chat model       : {CHAT_MODEL}  (fast, foreground)")
    print(f"  Extraction model : {EXTRACTION_MODEL}  (fast, background API)")
    print("  Conscious : local JSON file")
    print("  Subconscious : Cognee REST API (auto-consolidating)")
    print("  Commands: quit | status | /voice (hands-free) | /mute (speech toggle)")
    print("=" * 45 + "\n")

    update_heartbeat("listening")
    try:
        while True:
            try:
                # CPU De-confliction: run input in a separate thread so that the event loop can run background tasks
                user_input = await asyncio.to_thread(input, "You: ")
                user_input = user_input.strip()
            except EOFError:
                break

            if not user_input:
                continue

            cmd = user_input.lower()
            if cmd in {"quit", "exit", "bye"}:
                print("Shadow: Shutting down...")
                break
            if cmd == "consolidate":
                await memory_queue.join()
                await consolidate(background=False)
                continue
            if cmd == "status":
                print(memory_status())
                continue
            if cmd in {"/mute", "/m", "\\mute"}:
                voice_output_enabled = not voice_output_enabled
                status_str = "Muted." if not voice_output_enabled else "Unmuted."
                print(f"[Voice] {status_str}")
                continue
            if cmd in {"/voice", "/v", "\\voice"}:
                await run_hands_free_voice_loop()
                update_heartbeat("listening")
                continue

            print("Shadow: thinking...", end="\r", flush=True)
            reply = await think(user_input)
            print(f"Shadow: {reply}\n")
            update_heartbeat("listening")

    except KeyboardInterrupt:
        print("\nShadow: Interrupted — saving memory...")
    finally:
        update_heartbeat("offline")
        await shutdown(worker_task)
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        await stop_mcp_client()
        stop_cognee_server()


if __name__ == "__main__":
    asyncio.run(main())
