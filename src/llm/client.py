import os
import requests
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

def chat(prompt: str, system_prompt: str = None, port: int = None) -> str:
    """
    Unified chat client that supports both llama-server (direct completion port)
    and Ollama (OpenAI-compatible endpoint).
    """
    # 1. If a specific port is requested, use the llama-server completion API
    if port is not None:
        url = f"http://127.0.0.1:{port}/completion"
        formatted_prompt = prompt
        if system_prompt:
            formatted_prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
        
        payload = {
            "prompt": formatted_prompt,
            "n_predict": int(os.getenv("SHADOW_NUM_PREDICT", 300)),
            "temperature": 0.7,
            "stream": False
        }
        try:
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            return response.json().get("content", "").strip()
        except Exception as e:
            print(f"[LLM Client Error] Failed llama-server request at port {port}: {e}")
            # Fall through to Ollama fallback if llama-server fails

    # 2. Fall back to standard configured OpenAI-compatible endpoint (Ollama)
    endpoint = os.getenv("LLM_ENDPOINT", "http://localhost:11434/v1")
    model = os.getenv("LLM_MODEL", "qwen2.5:7b")
    headers = {"Authorization": f"Bearer {os.getenv('LLM_API_KEY', 'ollama')}"}
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": int(os.getenv("SHADOW_NUM_PREDICT", 300)),
        "stream": False
    }
    
    try:
        url = f"{endpoint.rstrip('/')}/chat/completions"
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[LLM Client Error] Ollama chat completion failed: {e}")
        return "I encountered an error communicating with the local model."

if __name__ == "__main__":
    print("Testing local LLM client...")
    res = chat("Hello! Who are you?")
    print("Response:", res)
