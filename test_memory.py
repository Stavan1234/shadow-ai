import os

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
os.environ["CACHING"] = "false"
os.environ["HUGGINGFACE_TOKENIZER"] = "nomic-ai/nomic-embed-text-v1.5"
os.environ["COGNEE_SKIP_CONNECTION_TEST"] = "true"

import asyncio
import cognee
from cognee.api.v1.search.search import SearchType

async def main():
    # Step 1: Fresh start
    print("Step 1: Pruning old data...")
    await cognee.prune.prune_system(metadata=True)
    print("✓ Done\n")

    # Step 2: Add memory
    print("Step 2: Adding memory...")
    await cognee.add("Stavan's AWS exam is on August 31st", dataset_name="facts")
    print("✓ Added\n")

    # Step 3: Build graph (this is the slow step — 2-5 min, DO NOT CLOSE)
    print("Step 3: Building knowledge graph... (this takes 2-5 min, wait!)")
    await cognee.cognify()
    print("✓ Graph built!\n")

    # Step 4: Search
    print("Step 4: Searching memory...")
    results = await cognee.search("When is the AWS exam?", query_type=SearchType.CHUNKS)
    if results:
        print("✓ SUCCESS! Memory works! Results:")
        for r in results:
            print("  →", r)
    else:
        print("✗ No results yet — but no error means pipeline worked!")

asyncio.run(main())