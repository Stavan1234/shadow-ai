# S.H.A.D.O.W. v4 — Rebuild Roadmap
*Lean, offline, Cognee-powered local assistant for a 16GB CPU-only laptop*

Hardware: Intel i5-8265U (4C/8T, no GPU), 16GB RAM, Windows 11
Constraint: Cognee is a **mandatory** hackathon requirement — kept, but moved fully off the interactive path.

---

## 0. The one rule that governs every decision below

> **Nothing touches the LLM or Cognee unless the router proves it must.**
> The model is the *brain* (reasoning, generation). Everything else — wake detection, transcription, routing, memory writes — must be handled by small, deterministic, or purpose-built tools so the 7B model is invoked as rarely as possible and only for the turns that actually need it.

---

## 1. Final Tool Stack

| Layer | Old | New | Why |
|---|---|---|---|
| Wake word | ASR-based keyword loop | **openWakeWord** | Purpose-built KWS model, near-zero CPU, no cloud, runs 24/7 in background |
| STT | `SpeechRecognition` (Google Web Speech API) | **faster-whisper** (`tiny.en` or `base.en`, INT8) | Fully offline (your old pipeline was secretly cloud-dependent), fast on CPU |
| TTS | `pyttsx3` / SAPI5 | **Piper** (`en_US-lessac-medium.onnx`) | Real-time on CPU, no COM/SAPI5 threading deadlocks, better voice quality |
| Model runtime | Ollama | **llama.cpp server** (`llama-server.exe`) | GBNF grammar-constrained output = valid tool calls every time, lower overhead than Ollama's daemon |
| Foreground model | `qwen2.5:7b` for everything | **`qwen2.5:3b-instruct-q4_k_m`** (chat) + `qwen2.5:7b-instruct-q4_k_m` (background only) | 3B model is 2-3x faster on CPU; reserve 7B for tasks with no user waiting |
| Router | Implicit / not enforced | **Explicit deterministic pre-router** (regex + tiny rules, code below) | Decides BEFORE any model/DB call whether memory/tools are even needed |
| Long-term memory | Cognee full pipeline on every turn | **Cognee, background-only, batched** | Satisfies hackathon requirement, removed from critical path entirely |
| Vector recall (fast path) | Cognee `/search` every turn | **Direct LanceDB query** (bypass Cognee's orchestration layer for simple recall) | Cognee's full search stack has overhead; raw LanceDB lookup is much faster for "did we talk about X" queries |
| Process lifecycle | Autostart everything at boot | **Sleep-by-default, wake-triggered** | Stops RAM/thermal pressure that's causing your reboots |
| Watchdog | Full-process kill+restart | **Per-subsystem health checks** | Restart only the subsystem that hung, not the whole stack |

---

## 2. Target Latency Budget

Set these as hard numbers you test against — not vibes.

| Stage | Budget | Notes |
|---|---|---|
| Wake word detection | <200ms | openWakeWord, continuous |
| STT (faster-whisper tiny.en, ~3s utterance) | <1.5s | CPU, INT8 |
| Router decision | <10ms | Pure Python, no I/O |
| Vector recall (LanceDB direct) | <150ms | Only if router says memory needed |
| MCP tool schema fetch | <50ms | Cache this at startup, don't refetch every turn |
| LLM first token (3B model) | <1.0s | This is your TTFT target |
| Full response (3B, ~60 tokens) | <4s | |
| TTS first audio | <500ms after first sentence | Stream sentence-by-sentence, don't wait for full response |
| **Total wake→speaking** | **<7s** | vs. your current multi-minute stalls |

---

## 3. Build Phases

### Phase 0 — Instrumentation & Repo Reset (Week 1)

1. Add a `perf_logger.py` that timestamps every stage boundary (wake, STT-start/end, router, memory, tools, LLM-start/first-token/end, TTS-start/end). Log to a local JSONL file per session.
2. Strip `shadow.py` down to a skeleton orchestrator with stub functions for each stage — you'll fill these in per phase below. This avoids editing a tangled 3000-line file live.
3. Keep your existing `.env`, `venv`, and Cognee cache folders — no need to reinstall those.

---

### Phase 1 — Voice I/O Rebuild (Weeks 2–4)

**Install:**
```bash
pip install faster-whisper openwakeword piper-tts sounddevice --break-system-packages
```

**Wake word loop (runs as its own lightweight always-on process, separate from the heavy orchestrator):**
```python
from openwakeword.model import Model
import sounddevice as sd
import numpy as np

oww = Model(wakeword_models=["hey_jarvis"])  # or train a custom "shadow" model

def audio_callback(indata, frames, time_info, status):
    prediction = oww.predict(indata[:, 0])
    if prediction["hey_jarvis"] > 0.5:
        trigger_wake()  # spins up the heavy orchestrator process

with sd.InputStream(channels=1, samplerate=16000, callback=audio_callback):
    while True:
        sd.sleep(100)
```

**STT (replace `record_voice_interactive`):**
```python
from faster_whisper import WhisperModel

stt_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")

def transcribe(audio_path):
    segments, _ = stt_model.transcribe(audio_path, beam_size=1, vad_filter=True)
    return " ".join(s.text for s in segments).strip()
```

**TTS (replace the pyttsx3 AudioWorker):**
```python
import subprocess

def speak(text, voice_model="en_US-lessac-medium.onnx"):
    subprocess.run(
        ["piper", "--model", voice_model, "--output-raw"],
        input=text.encode(), stdout=subprocess.PIPE
    )
    # pipe stdout to your audio playback of choice (sounddevice/pyaudio)
```
Stream sentence-by-sentence: split the LLM's streamed output on `. ! ?` and call `speak()` per sentence rather than waiting for the full response.

**Milestone check:** wake word → transcript → spoken echo, no LLM involved yet, should already feel instant.

---

### Phase 2 — Enforce the Router (Week 5)

This is the fix for "always went to subconscious memory." Make it explicit and impossible to bypass.

```python
import re

ACTION_KEYWORDS = re.compile(r"\b(create|delete|write|open|move|rename|list|find|run)\b", re.I)
MEMORY_KEYWORDS = re.compile(r"\b(remember|recall|what did i|last time|earlier|my project|previously)\b", re.I)
GREETING_KEYWORDS = re.compile(r"^\s*(hi|hey|hello|thanks|thank you|good (morning|night))\b", re.I)

def route(user_text: str) -> str:
    if GREETING_KEYWORDS.match(user_text):
        return "TIER_1_CHAT"          # no memory, no tools, straight to LLM
    if ACTION_KEYWORDS.search(user_text):
        return "TIER_3_ACTION"        # load MCP tools, skip memory unless also matched
    if MEMORY_KEYWORDS.search(user_text):
        return "TIER_2_MEMORY"        # vector recall only, no tools
    return "TIER_1_CHAT"              # default to cheapest path
```

Wire this so `TIER_1_CHAT` **cannot** call Cognee or MCP under any code path — not a soft preference, a hard branch. This one change alone should kill most of your latency.

---

### Phase 3 — Cognee, Done Right (Weeks 6–8)

You must use Cognee — so the fix is architectural placement, not removal.

**Rule: Cognee only ever runs in the background worker, never in the request/response path.**

- Keep your existing REST API server + `asyncio.Queue()` producer-consumer pattern from v3 — that part of your design was correct.
- Fact extraction and `/cognify` consolidation stay exactly as you had them: background, batched every 3 facts or 90s idle.
- **For live recall during conversation**, don't call Cognee's `/search` (which triggers its full orchestration layer). Instead query **LanceDB directly** with the embedding endpoint you already have configured:

```python
import lancedb

db = lancedb.connect(".data_storage_v3")
table = db.open_table("cognee_vectors")  # table Cognee already writes to

def fast_recall(query_embedding, top_k=3):
    return table.search(query_embedding).limit(top_k).to_list()
```

This still uses Cognee's data (it's writing to the same LanceDB store), satisfying the requirement, but the read path skips Cognee's heavier orchestration for the interactive turn.

- Keep `HUGGINGFACE_TOKENIZER=nomic-ai/nomic-embed-text-v1.5` and `CACHING=false` — those were correct fixes from v3.
- Fix the `search_type`/`query_type` field bug you already identified before doing anything else in this phase — verify it with a unit test, not a manual check.

**Milestone check:** run your `deep_test_shadow.py` "Subconscious Recall Persistence Test" and confirm recall still survives a simulated reboot, now measuring recall latency explicitly (<150ms target).

---

### Phase 4 — Model Runtime Swap (Weeks 9–11)

**Install llama.cpp** (prebuilt Windows binary, or build with CMake) and pull GGUF quantized models:
```bash
# via llama.cpp's model fetch or manually download GGUF from Hugging Face
llama-server.exe -m qwen2.5-3b-instruct-q4_k_m.gguf --port 8080 -c 2048
```

Run a **second instance on a different port** for the background 7B extraction model, launched only when the memory_worker actually needs it — not resident all the time:
```bash
llama-server.exe -m qwen2.5-7b-instruct-q4_k_m.gguf --port 8081 -c 2048
```

**Grammar-constrained tool calls** (eliminates malformed JSON retries):
```python
import requests, json

TOOL_GRAMMAR = open("tool_call.gbnf").read()  # define your MCP tool schema as a GBNF grammar

def call_llm_with_tools(prompt):
    resp = requests.post("http://127.0.0.1:8080/completion", json={
        "prompt": prompt,
        "grammar": TOOL_GRAMMAR,
        "n_predict": 300,
        "stream": True
    })
    return resp
```

Point your existing MCP client and tool-formatting code at this endpoint instead of Ollama's `/api/chat` — the request/response shape is similar enough that most of your orchestrator logic survives.

**Milestone check:** Tier-3 action commands (e.g., "create a folder named X") should now resolve in a single tool-call turn, not require retries.

---

### Phase 4.5 — Optional: Agent Reasoning Layer (Week 11, if time allows)

Oracle's open-source `agent-reasoning` package (`pip install agent-reasoning`) adds CoT / Self-Consistency / Tree-of-Thoughts / ReAct / self-reflection to any Ollama-served model via a drop-in proxy or Python class. Genuinely useful — but only if scoped correctly:

- **Do not** put it in front of Tier 1/2/3. ToT and Self-Consistency work by calling the model multiple times (branching search / k-sample voting), which multiplies your per-turn latency 3–10x — the opposite of everything Phase 2's router is trying to achieve.
- **Do** add a new **Tier 4: Deep Reasoning**, triggered only by explicit hard-reasoning queries (e.g. "figure out why X is failing," "compare these two approaches") — rare, latency-tolerant, and a strong demo moment.
- Use **Chain-of-Thought only** for Tier 4 in production (best accuracy/latency trade-off per their own docs); reserve ToT/Self-Consistency for a live demo flex, not default behavior.
- Route it through the background 7B model (port 8081 from Phase 4), never the interactive 3B model — keeps the voice loop untouched even when Tier 4 fires.

```python
DEEP_REASONING_KEYWORDS = re.compile(r"\b(figure out|debug|compare|why (is|does)|analyze)\b", re.I)
# in route(): check this before falling through to TIER_1_CHAT
if DEEP_REASONING_KEYWORDS.search(user_text):
    return "TIER_4_DEEP_REASONING"
```

```python
# Tier 4 only — proxy call to the background model, CoT strategy
import requests
resp = requests.post("http://127.0.0.1:8081/v1/reasoning", json={
    "prompt": user_text,
    "strategy": "cot",       # not "tot" in the live demo path unless you want the wait
    "model": "qwen2.5:7b"
})
```

---

### Phase 5 — Lifecycle Management (Weeks 12–13)

- Remove all subsystem launches from OS boot/startup scripts. Only the openWakeWord listener (Phase 1) runs persistently — it's small enough to idle all day.
- On wake trigger: spin up `llama-server` (3B), MCP filesystem server, and Cognee REST API. On N minutes idle (e.g., 5): tear them back down.
- Replace the single heartbeat/full-restart watchdog with **per-subsystem pings** (llama-server `/health`, Cognee `/health`, MCP process alive check). Restart only the dead one.

---

### Phase 6 — Testing & Acceptance (Week 14)

Re-run `deep_test_shadow.py` with the Phase 0 perf logger active, and gate merge on the Section 2 latency budget table. Add a new test: cold-boot-to-first-response time, since that's your actual demo-day metric for a hackathon.

---

## 4. What to explicitly tell Cursor/Antigravity when handing this off

- "Preserve the existing `.env`, Cognee cache folders, and REST API server pattern — do not reinitialize the knowledge graph."
- "The router in Phase 2 is a hard gate, not a hint — Tier 1 must be structurally incapable of calling Cognee or MCP."
- "Cognee calls only happen inside `memory_worker` (background thread/process), never inside the synchronous request handler."
- "Two separate llama.cpp server instances, different ports, different models — do not merge them back into one shared model like v3 did."

---

## 5. Success Criteria for the Hackathon Demo

- [ ] Cold start (wake word said, everything asleep) → first spoken response in under 10s
- [ ] Warm turn (subsystems already awake) → under 5s
- [ ] Cognee visibly used and demonstrable (e.g., "what's my project code name" recalls a fact stored 3 turns earlier or in a prior session)
- [ ] Zero cloud calls during the entire demo (verify with a packet monitor or just disconnect Wi-Fi and prove it still works)
- [ ] No forced restarts during a 15-minute continuous demo session
