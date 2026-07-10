import os
import sys
import asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Union

# Set system root directory environment variable BEFORE importing cognee
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
COGNEE_SYSTEM_PATH = PROJECT_ROOT / "data" / ".cognee_system_v4"
os.makedirs(COGNEE_SYSTEM_PATH, exist_ok=True)
os.environ["SYSTEM_ROOT_DIRECTORY"] = str(COGNEE_SYSTEM_PATH)

# Setup paths for python imports
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

# Load environment
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import cognee
import uvicorn

app = FastAPI(title="Cognee REST API Server")

class FactPayload(BaseModel):
    fact: Union[str, List[str]]

class SearchPayload(BaseModel):
    query: str
    limit: int = 5

@app.get("/health")
async def health():
    return {"status": "ok", "provider": os.getenv("VECTOR_DB_PROVIDER", "lancedb")}

@app.post("/add")
async def add_fact(payload: FactPayload):
    try:
        facts = payload.fact
        if isinstance(facts, str):
            facts = [facts]
            
        print(f"[Cognee Server] Adding {len(facts)} facts to database...")
        for fact in facts:
            await cognee.add(fact)
            
        return {"status": "added", "count": len(facts)}
    except Exception as e:
        print(f"[Cognee Server Error] Add failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/cognify")
async def cognify():
    try:
        print("[Cognee Server] Starting cognify consolidation pipeline...")
        await cognee.cognify()
        return {"status": "cognified"}
    except Exception as e:
        print(f"[Cognee Server Error] Cognify failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search")
async def search(payload: SearchPayload):
    try:
        print(f"[Cognee Server] Searching graph for query: '{payload.query}'...")
        results = await cognee.search(payload.query)
        # Parse results safely
        serializable_results = []
        for r in results:
            # results might contain objects or dicts, convert safely
            if hasattr(r, "dict"):
                serializable_results.append(r.dict())
            elif isinstance(r, dict):
                serializable_results.append(r)
            else:
                serializable_results.append(str(r))
        return {"results": serializable_results}
    except Exception as e:
        print(f"[Cognee Server Error] Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def start_server():
    port = int(os.getenv("COGNEE_API_PORT", 8002))
    print(f"[Cognee Server] Starting on port {port}...")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")

if __name__ == "__main__":
    start_server()
