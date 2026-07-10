import os
import sys
import asyncio
from pathlib import Path
from pypdf import PdfReader

# Setup project root path for safety
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.llm.client import chat
from src.memory.cognee_worker import memory_queue

def extract_text(file_path: str, max_chars: int = 6000) -> str:
    """
    Extracts text content from a given file path.
    Supports PDF and plain text formats (.txt, .md, etc.).
    """
    path = Path(file_path)
    if not path.exists():
        print(f"[Document QA Error] File does not exist at: {file_path}")
        return ""
        
    ext = path.suffix.lower()
    
    try:
        if ext == ".pdf":
            reader = PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return text[:max_chars]
        elif ext in [".txt", ".md", ".json", ".py", ".yaml", ".yml", ".ini", ".conf"]:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(max_chars)
        else:
            # Fallback/Attempt as text
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(max_chars)
    except Exception as e:
        print(f"[Document QA Error] Failed to read {file_path}: {e}")
        return ""

def answer_from_document(question: str, file_path: str) -> str:
    """
    Extracts content from document and answers the question using the primary chat model.
    """
    text = extract_text(file_path)
    if not text:
        return "I could not read the document content or the file was empty."
        
    prompt = (
        f"Document content:\n{text}\n\n"
        f"Question: {question}\n"
        f"Answer concisely, relying only on the document content above."
    )
    # We call the main chat model (port 8080/Ollama default)
    return chat(prompt, system_prompt="You are a helpful assistant answering questions about a document.")

async def queue_document_fact(file_path: str, question: str, answer: str):
    """
    Summarizes the Q&A in the background and enqueues a path-aware fact into the memory queue.
    """
    summary_prompt = (
        f"Summarize this Q&A about {file_path} in one concise sentence:\n"
        f"Q: {question}\n"
        f"A: {answer}"
    )
    # Use the background model (port 8081/Ollama fallback) to summarize
    print(f"[Document QA] Requesting background summary for {file_path}...")
    summary = await asyncio.to_thread(chat, summary_prompt, None, 8081)
    
    fact = f"File '{file_path}' — {summary}"
    print(f"[Document QA] Enqueuing fact: '{fact}'")
    await memory_queue.put(fact)
