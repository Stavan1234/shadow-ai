import os

def setup_environment():
    os.environ["ENABLE_BACKEND_ACCESS_CONTROL"] = "false"
    os.environ["LLM_PROVIDER"] = "ollama"
    os.environ["LLM_MODEL"] = "qwen2.5:14b"
    os.environ["LLM_ENDPOINT"] = "http://localhost:11434/v1"
    os.environ["LLM_API_KEY"] = "ollama"
    os.environ["EMBEDDING_PROVIDER"] = "ollama"
    os.environ["EMBEDDING_MODEL"] = "nomic-embed-text:latest"
    os.environ["EMBEDDING_ENDPOINT"] = "http://localhost:11434/api/embed"
    os.environ["EMBEDDING_API_KEY"] = "ollama"
    os.environ["EMBEDDING_DIMENSIONS"] = "768"
    os.environ["VECTOR_DB_PROVIDER"] = "lancedb"
    os.environ["GRAPH_DATABASE_PROVIDER"] = "ladybug"
    # os.environ["CACHING"] = "false"
    os.environ["CACHING"] = "true"
    os.environ["HUGGINGFACE_TOKENIZER"] = "nomic-ai/nomic-embed-text-v1.5"
    os.environ["COGNEE_SKIP_CONNECTION_TEST"] = "true"

MODEL = "qwen2.5:14b"
SESSION_ID = "shadow_session"
IMPROVE_EVERY_N_TURNS = 5

SHADOW_SYSTEM_PROMPT = """You are Shadow, a smart local AI assistant running 100% offline on this laptop.
You have persistent memory of important facts about the user.
Be concise, direct, and natural — like Jarvis. Don't mention being an AI model unless asked."""