import os
import sys
import requests
from pathlib import Path
import lancedb

# Setup project root path for safety
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / ".cognee_system_v4" / "databases" / "cognee.lancedb"

def get_query_embedding(query: str) -> list:
    """Generates a vector embedding for the query text using Ollama's local service."""
    endpoint = os.getenv("EMBEDDING_ENDPOINT", "http://localhost:11434/api/embed")
    model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text:latest")
    
    try:
        response = requests.post(endpoint, json={"model": model, "input": query}, timeout=5)
        response.raise_for_status()
        data = response.json()
        if "embeddings" in data and len(data["embeddings"]) > 0:
            return data["embeddings"][0]
        elif "embedding" in data:
            return data["embedding"]
        else:
            raise ValueError(f"Unexpected response format from embedding API: {data}")
    except Exception as e:
        print(f"[Fast Recall Error] Failed to get embedding for query '{query}': {e}")
        return []

def fast_recall(query: str, top_k: int = 3) -> list:
    """
    Directly queries LanceDB tables created by Cognee.
    Finds the most relevant matches for the query.
    """
    embedding = get_query_embedding(query)
    if not embedding:
        return []
        
    if not DB_PATH.exists():
        print(f"[Fast Recall] LanceDB database directory not found at {DB_PATH}")
        return []
        
    try:
        db = lancedb.connect(str(DB_PATH))
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tables = db.table_names()
        
        recalled_texts = []
        
        # We query the primary content tables containing '_text'
        target_tables = [t for t in tables if t.endswith("_text")]
        if not target_tables:
            target_tables = tables # Fallback to all tables
            
        for table_name in target_tables:
            tbl = db.open_table(table_name)
            # Query the table using the vector embedding
            results = tbl.search(embedding).limit(top_k).to_list()
            
            for row in results:
                # LanceDB results container distances, vector, and other fields
                # Extract text information from row or from nested payload
                text_content = ""
                
                # Check for standard fields
                if "text" in row and row["text"]:
                    text_content = row["text"]
                elif "value" in row and row["value"]:
                    text_content = row["value"]
                elif "payload" in row and isinstance(row["payload"], dict):
                    text_content = row["payload"].get("text", "")
                elif "payload" in row and isinstance(row["payload"], list) and len(row["payload"]) > 0:
                    payload = row["payload"][0]
                    if isinstance(payload, dict) and "text" in payload:
                        text_content = payload["text"]
                        
                distance = row.get("_distance", 1.0)
                
                if text_content:
                    recalled_texts.append({
                        "text": text_content.strip(),
                        "distance": distance,
                        "table": table_name
                    })
                    
        # Sort results by distance (lower distance = closer match)
        recalled_texts.sort(key=lambda x: x["distance"])
        return recalled_texts[:top_k]
        
    except Exception as e:
        print(f"[Fast Recall Error] LanceDB query failed: {e}")
        return []

if __name__ == "__main__":
    # Test fast recall
    import sys
    test_query = "What is the project name?" if len(sys.argv) < 2 else sys.argv[1]
    print(f"Recalling for: '{test_query}'")
    results = fast_recall(test_query)
    print("Results:")
    for r in results:
        print(f"- [{r['table']}](dist: {r['distance']:.4f}): {r['text']}")
