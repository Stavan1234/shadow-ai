# from config import setup_environment, MODEL, SESSION_ID, IMPROVE_EVERY_N_TURNS, SHADOW_SYSTEM_PROMPT
# setup_environment()

# import asyncio
# import cognee
# import ollama
# from cognee.api.v1.search.search import SearchType

# history = []
# turns_since_improve = 0


# async def recall(query: str) -> str:
#     """Fast subconscious lookup. Embedding search only, no LLM call."""
#     try:
#         results = await cognee.search(query, query_type=SearchType.CHUNKS, top_k=3)
#         texts = []
#         for r in results:
#             if isinstance(r, dict) and r.get("text"):
#                 texts.append(r["text"])
#         return "\n".join(texts)
#     except Exception:
#         return ""


# async def remember(user_msg: str, reply: str):
#     """Fast subconscious write. No LLM extraction — just a fire-and-forget log entry."""
#     try:
#         await cognee.remember(
#             f"User: {user_msg}\nShadow: {reply}",
#             session_id=SESSION_ID,
#             self_improvement=False,
#             run_in_background=True,
#         )
#     except Exception:
#         pass


# async def consolidate():
#     """Slow subconscious distillation. Runs the LLM extraction in one batch."""
#     global turns_since_improve
#     print("\n[Shadow is consolidating memory...]")
#     try:
#         await cognee.improve(session_ids=[SESSION_ID])
#         print("[Done]\n")
#     except Exception as e:
#         print(f"[Consolidation skipped: {e}]\n")
#     turns_since_improve = 0


# async def think(user_input: str) -> str:
#     global turns_since_improve

#     memory_context = await recall(user_input)

#     system_prompt = SHADOW_SYSTEM_PROMPT
#     if memory_context:
#         system_prompt += f"\n\nWhat you remember about the user:\n{memory_context}"

#     messages = [{"role": "system", "content": system_prompt}]
#     messages += history[-10:]
#     messages.append({"role": "user", "content": user_input})

#     # response = ollama.chat(model=MODEL, messages=messages)
#     response = ollama.chat(
#     model=MODEL,
#     messages=messages,
#     options={"num_ctx": 2048, "num_predict": 300}
# )
#     reply = response["message"]["content"]

#     history.append({"role": "user", "content": user_input})
#     history.append({"role": "assistant", "content": reply})

#     await remember(user_input, reply)
#     turns_since_improve += 1

#     if turns_since_improve >= IMPROVE_EVERY_N_TURNS:
#         await consolidate()

#     return reply


# async def main():
#     print("=" * 45)
#     print("  SHADOW AI  v2")
#     print(f"  Model : {MODEL}")
#     print("  Memory: Cognee (session + subconscious)")
#     print("  Type 'quit' to exit")
#     print("=" * 45 + "\n")

#     while True:
#         try:
#             user_input = input("You: ").strip()
#             if not user_input:
#                 continue
#             if user_input.lower() in ["quit", "exit", "bye"]:
#                 print("Shadow: Saving memory before I go...")
#                 await consolidate()
#                 print("Shadow: Goodbye.")
#                 break

#             print("Shadow: thinking...", end="\r")
#             reply = await think(user_input)
#             print(f"Shadow: {reply}\n")

#         except KeyboardInterrupt:
#             print("\nShadow: Quick save before shutdown...")
#             await consolidate()
#             break

# asyncio.run(main())


from config import setup_environment, MODEL, SHADOW_SYSTEM_PROMPT
setup_environment()

import asyncio
import json
import os
import cognee
import ollama
from datetime import datetime
from cognee.api.v1.search.search import SearchType

HISTORY_FILE = "conscious_memory.json"
MAX_HISTORY_TURNS = 10

# ---------- Conscious mind: simple, reliable, file-backed ----------

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[-MAX_HISTORY_TURNS * 2:], f, indent=2)

history = load_history()

# ---------- Subconscious mind: Cognee, but guarded against hallucination ----------

async def recall(query: str) -> str:
    """Only return memory if it's actually relevant. Empty otherwise — never invent."""
    try:
        results = await cognee.search(query, query_type=SearchType.CHUNKS, top_k=3)
        texts = []
        for r in results:
            if isinstance(r, dict) and r.get("text"):
                text = r["text"].strip()
                # Skip generic/empty placeholder chunks
                if len(text) > 15:
                    texts.append(text)
        return "\n".join(texts)
    except Exception:
        return ""

async def remember_fact(text: str):
    """Direct permanent write — slower but reliable. We batch-call this rarely, not every turn."""
    try:
        await cognee.add(text, dataset_name="shadow_memory")
    except Exception:
        pass

async def consolidate():
    """Run graph extraction on everything added since last consolidate. Call sparingly."""
    print("\n[Shadow is organizing long-term memory...]")
    try:
        await cognee.cognify()
        print("[Done]\n")
    except Exception as e:
        print(f"[Consolidation skipped: {e}]\n")

# ---------- Fact detection: lightweight, explicit, no silent LLM-only guessing ----------

FACT_TRIGGERS = [
    "my name is", "i am", "i'm", "remember that", "remember this",
    "don't forget", "my exam", "my deadline", "my birthday",
    "i work at", "i work as", "my job", "my goal", "due on", "due by",
]

def looks_like_fact(text: str) -> bool:
    lowered = text.lower()
    return any(trigger in lowered for trigger in FACT_TRIGGERS)

# ---------- Main think loop ----------

async def think(user_input: str) -> str:
    memory_context = await recall(user_input)

    system_prompt = SHADOW_SYSTEM_PROMPT
    if memory_context:
        system_prompt += (
            "\n\nFacts you remember about the user (only use these if relevant, "
            "never invent additional details beyond what's listed here):\n"
            f"{memory_context}"
        )
    else:
        system_prompt += (
            "\n\nYou have no stored facts about the user yet. "
            "If asked what you remember, say you don't have anything on record yet — "
            "do not invent facts."
        )

    messages = [{"role": "system", "content": system_prompt}]
    messages += history[-MAX_HISTORY_TURNS:]
    messages.append({"role": "user", "content": user_input})

    response = ollama.chat(
        model=MODEL,
        messages=messages,
        options={"num_ctx": 2048, "num_predict": 300},
    )
    reply = response["message"]["content"]

    history.append({"role": "user", "content": user_input})
    history.append({"role": "assistant", "content": reply})
    save_history(history)

    if looks_like_fact(user_input):
        await remember_fact(f"[{datetime.now().date()}] {user_input}")
        print("[Shadow noted that as worth remembering long-term]")

    return reply


async def main():
    print("=" * 45)
    print("  SHADOW AI  v2.1")
    print(f"  Model : {MODEL}")
    print("  Conscious memory: local file (fast, reliable)")
    print("  Subconscious memory: Cognee (facts only)")
    print("  Type 'quit' to exit, 'consolidate' to save long-term now")
    print("=" * 45 + "\n")

    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["quit", "exit", "bye"]:
                await consolidate()
                print("Shadow: Goodbye.")
                break
            if user_input.lower() == "consolidate":
                await consolidate()
                continue

            print("Shadow: thinking...", end="\r")
            reply = await think(user_input)
            print(f"Shadow: {reply}\n")

        except KeyboardInterrupt:
            await consolidate()
            break

asyncio.run(main())