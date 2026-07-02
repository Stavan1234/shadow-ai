# S.H.A.D.O.W. v4 — From-Scratch Build Guide
*Assume nothing exists. Every phase below can be handed to Antigravity as-is.*

Hardware: Intel i5-8265U (4C/8T, no GPU), 16GB RAM, Windows 11
Hard requirement: Cognee must be used, but only in the background (see Phase 3).

---

## 0. Before Phase 0 — Prerequisites Checklist

Get these installed/downloaded once, manually, before any agent touches code. Antigravity can walk you through each if you paste the relevant bullet as a `/grill-me` prompt.

- [ ] **Python 3.13** (you already had 3.13.5 — reinstall if gone)
- [ ] **Node.js LTS** (needed for the `@modelcontextprotocol/server-filesystem` MCP server)
- [ ] **Git** (for version control — non-negotiable this time, so you never lose the project again)
- [ ] **llama.cpp** — download prebuilt Windows binaries from the official releases, or build via CMake. You need `llama-server.exe`.
- [ ] **GGUF models** (download via Hugging Face, e.g. `bartowski` or `Qwen` repos):
  - `qwen2.5-3b-instruct-q4_k_m.gguf` (foreground chat)
  - `qwen2.5-7b-instruct-q4_k_m.gguf` (background extraction only)
- [ ] **Piper voice model**: `en_US-lessac-medium.onnx` + its `.onnx.json` config, from the Piper voices repo
- [ ] A working microphone, tested in Windows Sound Settings first (rules out a hardware issue before you debug software)

**Git init immediately.** First real command, before any code exists:
```bash
git init shadow-ai
cd shadow-ai
git add . && git commit -m "empty init"
```
Commit after every phase below. This is what protects you from another full-project wipe.

---

## 1. Project Structure (create this skeleton first)

```
shadow-ai/
├── .env                        # all config, see Phase 3
├── .gitignore
├── requirements.txt
├── venv/
├── src/
│   ├── orchestrator.py         # main loop, stage stubs
│   ├── wake/
│   │   └── listener.py         # openWakeWord, standalone process
│   ├── stt/
│   │   ├── transcribe.py       # faster-whisper wrapper
│   │   └── endpointing.py      # VAD-based silence detection
│   ├── tts/
│   │   └── speak.py            # Piper wrapper
│   ├── state/
│   │   └── machine.py          # ShadowState enum + status.json writer
│   ├── overlay/
│   │   ├── app.py              # pywebview host process
│   │   └── bubble.html         # Tailwind/CSS animated bubble
│   ├── router/
│   │   └── tiers.py            # deterministic router
│   ├── memory/
│   │   ├── cognee_worker.py    # background-only Cognee queue
│   │   ├── fast_recall.py      # direct LanceDB read path
│   │   └── document_qa.py      # PDF/doc extraction + path-aware Cognee facts
│   ├── fs/
│   │   └── index_watcher.py    # live directory index, no polling
│   ├── llm/
│   │   ├── client.py           # llama-server HTTP client
│   │   └── tool_call.gbnf      # grammar for tool calls
│   ├── tools/
│   │   └── mcp_client.py       # MCP stdio client
│   └── lifecycle/
│       ├── sleep_wake.py       # subsystem start/stop
│       └── watchdog.py         # per-subsystem health checks
├── models/                     # .gguf and .onnx files live here (gitignored)
├── data/
│   ├── .cognee_cache_v4/
│   ├── .cognee_system_v4/
│   └── .data_storage_v4/
├── logs/
│   └── perf_logger.py
└── tests/
    └── deep_test_shadow.py
```

Add `.gitignore` entries for `venv/`, `models/*.gguf`, `models/*.onnx`, `data/`, `logs/*.jsonl` — these are large/local-only, don't commit them.

---

## 2. Phase 0 — Environment & Instrumentation (Week 1)

### 2.1 Set up the venv and base dependencies
```bash
python -m venv venv
venv\Scripts\activate
pip install --upgrade pip
```

```
# requirements.txt — start with this, add per-phase below
cognee==1.2.2
lancedb
python-dotenv
fastapi
uvicorn
requests
psutil
pywin32
pypdf
watchdog
webrtcvad
pywebview
```
```bash
pip install -r requirements.txt --break-system-packages
```

### 2.2 Write `.env` from scratch
```
COGNEE_GRAPH_PROVIDER=ladybug
COGNEE_VECTOR_PROVIDER=lancedb
HUGGINGFACE_TOKENIZER=nomic-ai/nomic-embed-text-v1.5
ENABLE_BACKEND_ACCESS_CONTROL=false
CACHING=false
LLM_CHAT_PORT=8080
LLM_BACKGROUND_PORT=8081
COGNEE_API_PORT=8002
```
These settings are carried over deliberately from your v3 findings — they fixed real bugs (the caching hang, the tokenizer crash). Don't rediscover them the hard way.

### 2.3 Build `perf_logger.py` first, before any pipeline code
```python
import time, json, os

class PerfLogger:
    def __init__(self, path="logs/session.jsonl"):
        self.path = path
        self.events = []

    def mark(self, stage: str):
        self.events.append({"stage": stage, "t": time.time()})

    def flush(self, session_id: str):
        with open(self.path, "a") as f:
            f.write(json.dumps({"session": session_id, "events": self.events}) + "\n")
        self.events = []
```
Every phase from here on calls `perf.mark("stage_name")` at entry/exit. This is how you'll know Phase 1–4 actually hit the latency budget instead of guessing.

### 2.4 Conscious memory (short-term — separate from Cognee entirely)

This is not Cognee, and it doesn't go through the memory queue. It's a plain rolling buffer + file mirror, and it stays because it's nearly free:

```python
# src/memory/conscious.py
import json, time

MAX_TURNS = 10

class ConsciousMemory:
    def __init__(self, path="data/conscious_memory.json"):
        self.path = path
        self.turns = []
        self.last_session_summary = ""
        self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                d = json.load(f)
                self.turns = d.get("turns", [])
                self.last_session_summary = d.get("last_session_summary", "")
        except FileNotFoundError:
            pass

    def add_turn(self, role: str, text: str):
        self.turns.append({"role": role, "text": text, "t": time.time()})
        self.turns = self.turns[-MAX_TURNS:]
        self._flush()

    def _flush(self):
        with open(self.path, "w") as f:
            json.dump({"turns": self.turns, "last_session_summary": self.last_session_summary}, f)
```

Used for: injecting the last 10 turns + last session summary into the prompt, and surviving crashes/restarts. It never calls Cognee, never hits the network, never blocks — it's just a dict and a file write. Keep it exactly this simple; there's no reason to route this through the async queue.

### 2.5 Orchestrator skeleton

Create `src/orchestrator.py` with empty stage functions (`wake→stt→route→recall→tools→infer→tts`) that just log and pass through a dummy string end-to-end. Get this "hello world" loop running before adding any real subsystem — it proves your process wiring works before you add complexity on top.

**Milestone check:** running `python src/orchestrator.py` with a hardcoded fake transcript should print a hardcoded fake response and produce a valid `logs/session.jsonl`.

---

## 3. Phase 1 — Voice I/O (Weeks 2–4)

### 3.1 Wake word (`src/wake/listener.py`)
```bash
pip install openwakeword sounddevice numpy
```
Download the pretrained `hey_jarvis` model first (ships with the package) to prove the pipeline works before attempting a custom "shadow" wake word — custom wake word training is its own side-quest, don't block on it.

```python
from openwakeword.model import Model
import sounddevice as sd

oww = Model(wakeword_models=["hey_jarvis"])

def start_listener(on_wake):
    def callback(indata, frames, time_info, status):
        pred = oww.predict(indata[:, 0])
        if pred["hey_jarvis"] > 0.5:
            on_wake()
    with sd.InputStream(channels=1, samplerate=16000, callback=callback):
        while True:
            sd.sleep(100)
```
This runs as its **own OS process**, not inside the orchestrator — launch it via a small `run_listener.py` entrypoint. It should idle at low CPU% all day; verify in Task Manager.

**Milestone:** say "hey jarvis," confirm a console print fires within ~200ms.

### 3.2 STT (`src/stt/transcribe.py`)
```bash
pip install faster-whisper
```
```python
from faster_whisper import WhisperModel

model = WhisperModel("tiny.en", device="cpu", compute_type="int8")

def transcribe(audio_path: str) -> str:
    segments, _ = model.transcribe(audio_path, beam_size=1, vad_filter=True)
    return " ".join(s.text for s in segments).strip()
```
You still need something to *record* the audio into a file/buffer first — reuse `sounddevice` to capture ~5–8 seconds after wake, write to a temp WAV, pass the path in.

**Verify offline-ness explicitly**: disconnect Wi-Fi, run a transcription, confirm it still works. This is the check your old pipeline would have failed.

### 3.3 TTS (`src/tts/speak.py`)
```bash
pip install piper-tts
```
Place `en_US-lessac-medium.onnx` + `.json` in `models/`.
```python
import subprocess

def speak(text: str):
    subprocess.run(
        ["piper", "--model", "models/en_US-lessac-medium.onnx",
         "--output_file", "logs/out.wav"],
        input=text.encode()
    )
    # play logs/out.wav via sounddevice or winsound
```
Get single-sentence synthesis working first. Sentence-streaming (splitting LLM output on `.!?` and speaking incrementally) is the optimization — add it only after the basic path works, in Phase 4 once the LLM is wired in.

### 3.4 Endpointing — fixes "starts executing the instant I pause"

Your fixed-duration recording (`record for 5-8s`) is exactly why it feels trigger-happy on a pause — it either cuts you off mid-thought or fires on the first silence gap. Replace it with **silence-based endpointing using VAD**, not a timer:

```bash
pip install webrtcvad
```
```python
# src/stt/endpointing.py
import webrtcvad, collections

vad = webrtcvad.Vad(2)  # aggressiveness 0-3; 2 is a good default for a quiet room

def record_until_silence(stream, sample_rate=16000, frame_ms=30,
                          silence_hangover_ms=1200, max_duration_s=15):
    """
    Keeps recording as long as speech is detected. Only finalizes after
    `silence_hangover_ms` of continuous silence — a genuine pause-to-think
    resets the timer instead of ending the utterance.
    """
    frames = []
    silence_run_ms = 0
    frame_bytes = int(sample_rate * frame_ms / 1000) * 2
    while True:
        frame = stream.read(frame_bytes)
        frames.append(frame)
        if vad.is_speech(frame, sample_rate):
            silence_run_ms = 0
        else:
            silence_run_ms += frame_ms
        if silence_run_ms >= silence_hangover_ms:
            break
        if len(frames) * frame_ms / 1000 >= max_duration_s:
            break
    return b"".join(frames)
```

`silence_hangover_ms=1200` is your tunable "sufficient delay" — the utterance only finalizes after 1.2s of true silence, so a mid-sentence pause to gather your words doesn't get treated as "done." Use the **same function, with a shorter hangover (~800ms)** for capturing the yes/no confirmation response — that one should feel snappier since it's a single word, not a sentence.

### 3.5 State machine — formalizes what "busy" means

Right now there's no single source of truth for "is Shadow listening, thinking, or speaking" — that's *why* talking during processing does nothing silently instead of doing something sensible. Add one explicit state machine that everything else (overlay, filler phrases, mic gating) reads from:

```python
# src/state/machine.py
from enum import Enum, auto

class ShadowState(Enum):
    ASLEEP = auto()          # only wake-word listener running
    LISTENING = auto()       # recording user speech
    PROCESSING = auto()      # LLM/tools/memory working
    CONFIRMING = auto()      # waiting on yes/no
    SPEAKING = auto()        # TTS playing

_state = ShadowState.ASLEEP
_subscribers = []  # overlay + filler logic subscribe to changes

def set_state(new_state: ShadowState):
    global _state
    _state = new_state
    for cb in _subscribers:
        cb(new_state)
```
Write current state to `data/status.json` on every change too — that's the cheapest possible IPC for the overlay widget (Section 3.7) to read from, no sockets needed for v1.

### 3.6 Instant filler feedback — "just a moment, Sir"

The fix for "I talked and nothing happened" isn't a smarter model, it's **near-zero-latency acknowledgment that doesn't wait for the LLM at all**. Pre-synthesize a handful of filler phrases with Piper **once, at startup**, cache them as WAV files, and play a random one the instant `PROCESSING` state begins — this is playing an existing file, not running Piper live, so it's <100ms:

```python
FILLERS = ["Just a moment, Sir.", "Working on it.", "One second.", "Let me check."]

def pre_render_fillers():
    for i, phrase in enumerate(FILLERS):
        piper_synthesize(phrase, out_path=f"data/filler_{i}.wav")  # done once at startup

def play_random_filler():
    import random
    play_wav(f"data/filler_{random.randint(0, len(FILLERS)-1)}.wav")
```
Call `play_random_filler()` the moment `set_state(ShadowState.PROCESSING)` fires, in parallel with the actual LLM call starting — don't wait for one before the other.

**If the user keeps talking while PROCESSING:** don't try true barge-in (interrupting a live inference) — on this hardware that's a rabbit hole with a bad cost/benefit. Instead, buffer the new audio and once the current turn finishes speaking, either fold it into the next turn's context or just process it as a fresh turn. Simple, predictable, no half-finished interruption bugs.

### 3.7 Visual overlay — Siri-style bubble (bottom-right)

Keep this decoupled and lightweight — it should be a tiny widget reading `data/status.json`, not something wired into the model pipeline.

```bash
pip install pywebview
```
```python
# src/overlay/app.py
import webview, json, time, threading

def poll_status():
    while True:
        with open("data/status.json") as f:
            state = json.load(f)["state"]
        window.evaluate_js(f"updateBubbleState('{state}')")
        time.sleep(0.2)

window = webview.create_window(
    "Shadow", "src/overlay/bubble.html",
    width=140, height=140, frameless=True, on_top=True,
    transparent=True, x=1750, y=900  # bottom-right corner, adjust to your resolution
)
threading.Thread(target=poll_status, daemon=True).start()
webview.start()
```
`src/overlay/bubble.html` — a single-file Tailwind (via CDN) + CSS animation bubble with 4 visual states (idle pulse, listening ring, thinking spinner, speaking waveform), driven by a `updateBubbleState(state)` JS function that swaps a CSS class. This runs as its **own separate process** — if it crashes or lags, it never touches the voice pipeline. This is the right place to hand Antigravity a `/browser`-flavored prompt, since it can iterate on the animation visually and screenshot-verify it.

### 3.8 Sleep word — full teardown, not just "stop listening"

Add a second, always-checked phrase that bypasses the router entirely and tears everything down — reusing the Phase 5 sleep/wake teardown logic (Section 8.1), just triggered by voice instead of only by idle timeout:

```python
SLEEP_PHRASES = {"go to sleep shadow", "shadow go to sleep", "shadow sleep now"}

def check_sleep_command(transcript: str) -> bool:
    return transcript.strip().lower() in SLEEP_PHRASES

# in the orchestrator, checked BEFORE router.route() on every transcript:
if check_sleep_command(transcript):
    speak("Going to sleep, Sir.")
    teardown_subsystems()   # same function Phase 5's idle-timeout calls
    set_state(ShadowState.ASLEEP)
    return
```
Keep the phrase list exact-match rather than fuzzy/regex — you do not want "sleep" fuzzy-matching against unrelated speech and tearing down mid-conversation. This is the one place in the whole system where being overly strict is correct.

**Milestone check for all of Phase 1:** wake word → record → transcribe → speak back the transcript verbatim (no LLM yet). This full loop should complete in under 3 seconds. Log it with `perf_logger` and confirm.

> **Note:** this verbatim echo is an *audio-hardware sanity check only* — it proves mic→STT→speaker works end to end. It is **not** the final UX. Final behavior uses LLM-paraphrased intent confirmation, not transcript playback — see Section 6.5.

**Additional Phase 1 milestone:** say a command, pause 1s mid-sentence, resume speaking — confirm the recording does *not* finalize during your pause. Say "go to sleep shadow" — confirm the wake-word listener is the only process still running afterward (check Task Manager).

---

## 4. Phase 2 — Router (Week 5)

Router is pure Python, no dependencies. Build `src/router/tiers.py` exactly as scoped in the previous plan (regex-based Tier 1/2/3/4 classification). Write it as a standalone module with unit tests **before** wiring it into the orchestrator — you want to prove the tiering logic in isolation first.

```python
import re

GREETING = re.compile(r"^\s*(hi|hey|hello|thanks|good (morning|night))\b", re.I)
ACTION = re.compile(r"\b(create|delete|write|open|move|rename|list|find|run)\b", re.I)
MEMORY = re.compile(r"\b(remember|recall|what did i|last time|earlier|my project)\b", re.I)
DEEP = re.compile(r"\b(figure out|debug|compare|why (is|does)|analyze)\b", re.I)
DOCUMENT = re.compile(r"\.(pdf|docx|txt|md)\b|\bthis (document|file|pdf)\b|\bin (the )?(pdf|document)\b", re.I)

def route(text: str) -> str:
    if DOCUMENT.search(text): return "TIER_5_DOCUMENT_QA"
    if DEEP.search(text): return "TIER_4_DEEP_REASONING"
    if GREETING.match(text): return "TIER_1_CHAT"
    if ACTION.search(text): return "TIER_3_ACTION"
    if MEMORY.search(text): return "TIER_2_MEMORY"
    return "TIER_1_CHAT"
```

Write `tests/test_router.py` with ~15 example phrases per tier before moving on. This is the module that failed silently last time ("always went to subconscious memory") — pin it down with tests now so it can't regress.

---

## 5. Phase 3 — Cognee, Correctly Scoped (Weeks 6–8)

Since you're rebuilding from zero, do this in strict order — each step depends on the last actually working.

### 5.1 Install and smoke-test Cognee alone, no orchestrator involved
```bash
pip install cognee==1.2.2 lancedb
```
Write a throwaway `scratch_test_cognee.py` that just does `cognee.add("test fact")` then `cognee.cognify()` then `cognee.search("test")` and prints the result. Get this working standalone first — don't debug Cognee integration issues inside a half-built orchestrator.

### 5.2 Stand up the Cognee REST API server
Recreate the decoupled server pattern from your v3 report: a small FastAPI wrapper exposing `/add`, `/cognify`, `/search` that internally calls the Cognee Python SDK. This is what lets the orchestrator talk to Cognee over HTTP instead of importing it directly into the hot path.

### 5.3 Build the background worker (`src/memory/cognee_worker.py`)
```python
import asyncio

memory_queue = asyncio.Queue()

async def memory_worker():
    fact_count = 0
    while True:
        fact = await memory_queue.get()
        await post_to_cognee_add(fact)          # HTTP call to your REST server
        fact_count += 1
        if fact_count >= 3 or queue_idle_for(90):
            await post_to_cognee_cognify()
            fact_count = 0
```
This is the only place in the entire codebase allowed to call Cognee's `/add` or `/cognify`. Enforce it with a code comment and a test (Phase 6 will assert this structurally).

### 5.4 Build the fast recall path (`src/memory/fast_recall.py`)
```python
import lancedb

db = lancedb.connect("data/.data_storage_v4")

def fast_recall(query_embedding, top_k=3):
    table = db.open_table("cognee_vectors")   # table name Cognee writes to — verify via db.table_names()
    return table.search(query_embedding).limit(top_k).to_list()
```
This reads the *same data* Cognee wrote, satisfying the requirement to genuinely use Cognee's knowledge graph — it just skips Cognee's own orchestration layer for the interactive-turn read.

**Milestone check:** feed 5 fake facts through the queue, wait for consolidation, kill and restart the process, confirm `fast_recall()` still returns them. This is your v3 "Subconscious Recall Persistence Test," rebuilt.

---

### 5.5 Document Q&A — Tier 5 (`src/memory/document_qa.py`)

This is the "read rainbow.pdf and answer" scenario. Two jobs happen, on different timelines: **answer now** (foreground, no Cognee) and **remember for later** (background, via the same queue as everything else).

```python
from pypdf import PdfReader   # already in your original requirements.txt

def extract_text(pdf_path: str, max_chars: int = 6000) -> str:
    reader = PdfReader(pdf_path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return text[:max_chars]   # keep inside the 3B model's 2048-token context; chunk later if needed

def answer_from_document(question: str, pdf_path: str) -> str:
    text = extract_text(pdf_path)
    prompt = f"Document content:\n{text}\n\nQuestion: {question}\nAnswer concisely based only on the document."
    return chat(prompt, port=8080)   # foreground 3B model, answers immediately
```

**The part that makes it findable later** — push a fact to the memory queue that embeds the path, not just the content, so a future vector search on "that document about X" surfaces both the summary and where the file lives:

```python
async def queue_document_fact(pdf_path: str, question: str, answer: str):
    summary_prompt = f"Summarize this Q&A about {pdf_path} in one sentence: Q: {question} A: {answer}"
    summary = await chat_background(summary_prompt, port=8081)  # background 7B model, no rush
    fact = f"File '{pdf_path}' — {summary}"   # path is literally embedded in the text that gets embedded
    await memory_queue.put(fact)
```

Orchestrator flow for Tier 5:
```python
answer = answer_from_document(question, resolved_path)
speak(answer)
asyncio.create_task(queue_document_fact(resolved_path, question, answer))  # fire-and-forget, doesn't block TTS
```

Later, when you ask "what was that document about the rainbow thing," Tier 2 fires, `fast_recall()` finds the fact (Section 5.4), and because the path is embedded in the fact text itself, Shadow can answer *and* tell you where the file is — no separate lookup table needed, Cognee's own storage does double duty.

**Note on `resolved_path`:** where does that come from if you just said "rainbow.pdf" with no folder? See Section 6.6 — same directory-index mechanism resolves this too.

---

## 6. Phase 4 — Model Runtime (Weeks 9–11)

### 6.1 Run two llama-server instances
```bash
llama-server.exe -m models/qwen2.5-3b-instruct-q4_k_m.gguf --port 8080 -c 2048
llama-server.exe -m models/qwen2.5-7b-instruct-q4_k_m.gguf --port 8081 -c 2048
```
Run these manually in two terminals first to confirm both load and respond to a plain `curl` request before wiring anything else to them. On 16GB RAM, watch Task Manager — if both are loaded simultaneously you may be tight on memory; consider only starting 8081 on-demand (Phase 5 handles this properly).

### 6.2 Tool-call grammar
Write `src/llm/tool_call.gbnf` describing valid JSON shapes for your MCP tool calls (start with just `create_directory`, `write_file`, `read_file`, `list_directory` — the four you'll actually demo, not all 44). Expand later.

### 6.3 Wire the LLM client
```python
import requests

def chat(prompt: str, port: int = 8080, grammar: str = None):
    payload = {"prompt": prompt, "n_predict": 300, "stream": True}
    if grammar:
        payload["grammar"] = grammar
    return requests.post(f"http://127.0.0.1:{port}/completion", json=payload, stream=True)
```

### 6.4 MCP client
Reuse the Node.js `@modelcontextprotocol/server-filesystem` approach from before — launch it as a stdio subprocess, call `list_tools()` once at startup and cache the schema (don't refetch every turn, that was pure waste in v3).

### 6.5 Intent confirmation (Tier 3 only — replaces raw transcript echo)

The point of confirmation is "did the model understand me," not "did the mic hear me correctly." So the model itself produces the confirmation phrase, in the same inference pass that proposes the tool call — no separate LLM round-trip needed.

Extend `tool_call.gbnf` so a Tier 3 response is forced into this shape:
```json
{"intent_summary": "Create a folder named Orion", "tool_call": {"name": "create_directory", "args": {"path": "Orion"}}}
```

Orchestrator flow for Tier 3:
```python
result = chat(prompt, port=8080, grammar=TOOL_GRAMMAR)
parsed = json.loads(result)
speak(parsed["intent_summary"] + ". Should I proceed?")
confirmation = transcribe(record_short_clip())   # listens for yes/no only
if is_affirmative(confirmation):
    execute_tool(parsed["tool_call"])
    speak("Done.")
else:
    speak("Okay, cancelled.")
```

This way a mangled, stuttered "uh create create a folder um named- named Orion" still gets confirmed back as the clean sentence above — because the LLM's job here is exactly to extract intent from messy speech, which is what it's good at and a regex string-cleaner (your v3 approach) is not.

Tier 1/2 skip this entirely — they answer directly, no confirmation step.

**Milestone check:** Tier 3 action ("create a folder named test") resolves via intent_summary confirmation → yes → single grammar-constrained tool call, no retries, under the 5s foreground budget plus the yes/no round-trip (~2–3s more).

### 6.6 Filesystem awareness index (why Shadow keeps asking where things are)

The reason your old build kept asking "where should I save this" is that path resolution was left entirely to the model — it has no idea what's on your disk unless it calls `list_directory` and reads the result, which is slow and still ambiguous. Fix this with a **live index the model never has to compute itself**:

```bash
pip install watchdog
```

```python
# src/fs/index_watcher.py
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import os, json, difflib

WATCHED_ROOTS = [r"C:\Users\HP\Desktop", r"C:\Users\HP\Documents", r"C:\Users\HP\shadow-ai"]
INDEX_PATH = "data/directory_index.json"
_index = {}  # name -> full path, kept in memory, mirrored to disk

def _rebuild_initial():
    for root in WATCHED_ROOTS:
        for dirpath, dirs, files in os.walk(root):
            for name in dirs + files:
                _index[name] = os.path.join(dirpath, name)
    _flush()

def _flush():
    with open(INDEX_PATH, "w") as f:
        json.dump(_index, f)

class Handler(FileSystemEventHandler):
    def on_created(self, event):
        _index[os.path.basename(event.src_path)] = event.src_path; _flush()
    def on_deleted(self, event):
        _index.pop(os.path.basename(event.src_path), None); _flush()
    def on_moved(self, event):
        _index.pop(os.path.basename(event.src_path), None)
        _index[os.path.basename(event.dest_path)] = event.dest_path; _flush()

def start_watcher():
    _rebuild_initial()   # one full scan, only at startup
    observer = Observer()
    for root in WATCHED_ROOTS:
        observer.schedule(Handler(), root, recursive=True)
    observer.start()

def resolve_path(name: str) -> list[str]:
    """Returns candidate full paths for a bare filename mentioned in speech."""
    matches = difflib.get_close_matches(name, _index.keys(), n=3, cutoff=0.6)
    return [_index[m] for m in matches]
```

This costs **one full scan at startup**, then updates instantly and for free on every create/delete/rename — no periodic re-scan, no LLM call, no polling loop burning CPU. It runs as its own lightweight background thread alongside the wake-word listener from Phase 1.

**How the model uses it — never asked to guess, only to pick:**
```python
candidates = resolve_path("rainbow.pdf")
if len(candidates) == 1:
    resolved_path = candidates[0]                  # auto-resolved, no round-trip
elif len(candidates) > 1:
    speak(f"I found a few matches: {', '.join(candidates)}. Which one?")  # rare, only on real ambiguity
else:
    resolved_path = os.path.join(WATCHED_ROOTS[-1], name)  # sensible default for new files (create actions)
```

Feed the resolved candidate(s) into the tool-call grammar as enum values rather than letting the model free-generate a path string — this is what actually eliminates the back-and-forth, not a smarter prompt.



---

## 7. Phase 4.5 — Agent Reasoning (Optional, Week 11)

```bash
pip install agent-reasoning
```
Wire it only behind `TIER_4_DEEP_REASONING`, pointed at port 8081 (background model), default strategy `cot`. See router code in Section 4 — the `DEEP` regex already routes here.

---

## 8. Phase 5 — Lifecycle Management (Weeks 12–13)

### 8.1 Sleep/wake (`src/lifecycle/sleep_wake.py`)
On boot: only `run_listener.py` (Phase 1 wake word process) starts. Nothing else.
On wake trigger: spawn `llama-server` (port 8080), the MCP filesystem server, and the Cognee REST API as subprocesses.
On 5 minutes idle: terminate those three subprocesses (`taskkill` or `subprocess.terminate()`), freeing RAM.
The port-8081 background model only spawns when `memory_worker` actually has a batch ready — not kept resident.

### 8.2 Watchdog v2 (`src/lifecycle/watchdog.py`)
Replace the single full-process heartbeat kill from v3 with three independent checks, each restarting only its own subsystem:
```python
def check_llm(): return requests.get("http://127.0.0.1:8080/health", timeout=2).ok
def check_cognee(): return requests.get("http://127.0.0.1:8002/health", timeout=2).ok
def check_mcp(): return mcp_process.poll() is None
```
Run this loop every 10s; restart whichever check fails, leave the others untouched.

---

## 9. Phase 6 — Testing & Demo Prep (Week 14)

Build `tests/deep_test_shadow.py` with these assertions, gated against the budget table below:

| Stage | Budget |
|---|---|
| Wake detection | <200ms |
| STT (faster-whisper tiny.en, ~5s clip) | <1.5s |
| Router decision | <10ms |
| Fast recall (LanceDB) | <150ms |
| LLM first token (3B) | <1.0s |
| Full response (3B, ~60 tokens) | <4s |
| Cold wake→speaking (everything asleep) | <10s |
| Warm wake→speaking (Tier 1/2, no confirmation) | <5s |
| Warm wake→speaking (Tier 3, incl. confirmation round-trip) | <8s |
| Filler phrase playback after PROCESSING starts | <150ms |
| Sleep word → full subsystem teardown | <3s |

Add a 15-minute continuous-session stress test mixing all 4 tiers, and a "prove it's offline" test that disconnects networking and runs a full turn successfully.

---

## 10. Suggested order to hand this to Antigravity

Work phase by phase, one Antigravity session per phase, commit to git after each milestone check passes. Don't start Phase 2 until Phase 1's milestone is genuinely met — on this hardware, debugging two new subsystems at once is how you end up back where you started.

---

## 11. Expert Review — Bugs This New Design Could Introduce, and How to Harden It

Adding the endpointing, state machine, overlay, and sleep word doesn't just fix your three complaints — it introduces new coordination surfaces that didn't exist before. Going through them honestly:

### 11.1 Echo/feedback loop (new bug, not in your old design's failure list, but latent)
With Piper now streaming sentence-by-sentence while openWakeWord listens continuously in its own process, Shadow's own voice can trigger the wake word or get transcribed as a fake command. **Mute the wake-word listener and STT capture during `SPEAKING` state**, with a ~500ms cooldown after playback ends (room echo tail) before re-arming — same root cause as your old Section D bug, now with a formal state to hang the fix on instead of an ad-hoc sleep.

### 11.2 Cross-process IPC — needs to be explicit, not assumed
You now have **four separate OS processes**: wake-word listener, main orchestrator, overlay widget, and (on-demand) llama-server/Cognee/MCP subprocesses. `asyncio.Queue()` only works *within* one process — it will silently do nothing useful if the wake listener and orchestrator are separate processes and you assume they share memory. Use the simplest thing that works for a hackathon timeline: the wake listener POSTs to a local HTTP endpoint (`http://127.0.0.1:8090/wake`) that the orchestrator exposes, and the overlay reads `data/status.json` by polling (already specified in 3.7). Don't reach for sockets/gRPC here — HTTP-on-localhost and a JSON file are the two IPC mechanisms this whole build needs, don't add a third.

### 11.3 RAM budget — do the arithmetic before you build, not during the demo
Rough resident-memory add-up at peak (wake trigger, mid Tier-3 action, 3B model loaded, Cognee awake):
- 3B Q4 model: ~2GB
- faster-whisper tiny.en: ~200MB
- Cognee + LanceDB + embedding model: ~1.5-2GB
- Piper: ~150MB
- Windows + background processes: ~3-4GB

That's roughly 7-9GB, leaving headroom on 16GB — **as long as the 7B background model is never resident at the same time as everything else**, which is why Phase 5's "spawn on demand, don't keep loaded" rule for port 8081 isn't optional polish, it's the difference between fitting and swapping. Worth a real Task Manager check during Phase 4's milestone, not just an assumption.

### 11.4 Watchdog directory watcher edge cases
Windows sometimes reports a rename as a delete+create pair rather than a clean `on_moved` event, especially across drives — your `_index` could end up with a stale entry. Not worth engineering around for a hackathon; just have `resolve_path()` fall back to a live `os.path.exists()` check on the top candidate before acting, cheap enough to not matter, and it silently self-heals the common case.

### 11.5 Sleep word vs. accidental trigger during normal conversation
Because Section 3.8 uses exact-match rather than fuzzy matching, this is already low-risk. One more guard worth adding: **require the sleep phrase to be the *entire* utterance**, not just present somewhere in it — this stops "should shadow go to sleep now, or should I keep working" from accidentally tearing everything down mid-sentence.

### 11.6 Smarter/lighter opportunities worth taking now, not bolting on later
- **Cache the MCP tool schema once at orchestrator startup**, not per-turn (flagged in Phase 4 already, restating because it's an easy miss) — this was measurable dead weight in your v3 report.
- **Skip the confirmation step for read-only Tier 3 actions** (`list_directory`, `read_file`) — only gate destructive ones (`create`, `delete`, `write`, `move`, `rename`) behind the yes/no round-trip. You flagged this as worth trimming earlier — now's the point to actually decide and encode it in `ACTION` tier logic as a sub-classification.
- **The filler-phrase cache (3.6) can double as your "Shadow is offline" indicator** — if `llama-server` fails to respond within ~2s of a request, play a filler ("still working on it, Sir") automatically as a retry-masking technique rather than the user experiencing dead air while a health check figures out something's wrong.
- **Don't train a custom "Shadow" wake word until everything else is solid.** `hey_jarvis` is free, pretrained, and works immediately — recognize this is not a place to spend hackathon time until the rest of the pipeline is proven end-to-end.


