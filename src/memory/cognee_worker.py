import asyncio
import os
import requests
from pathlib import Path

# Queue for incoming memory facts to be processed in the background
memory_queue = asyncio.Queue()

async def memory_worker():
    """
    Background worker that monitors memory_queue.
    It posts new facts to the Cognee REST API server (/add)
    and periodically triggers the cognification/consolidation process (/cognify).
    """
    print("[Memory Worker] Started and listening on queue...")
    fact_count = 0
    COGNIFY_THRESHOLD = 3
    IDLE_TIMEOUT = 90.0  # seconds to wait before auto-cognifying pending facts
    
    server_port = os.getenv("COGNEE_API_PORT", "8002")
    base_url = f"http://127.0.0.1:{server_port}"
    
    while True:
        try:
            # Wait for next item in the queue with a timeout
            try:
                fact = await asyncio.wait_for(memory_queue.get(), timeout=IDLE_TIMEOUT)
                
                print(f"[Memory Worker] Posting fact to Cognee: '{fact}'")
                # Perform the HTTP call to add fact
                resp = await asyncio.to_thread(
                    requests.post, 
                    f"{base_url}/add", 
                    json={"fact": fact}, 
                    timeout=10
                )
                
                if resp.status_code == 200:
                    fact_count += 1
                    print(f"[Memory Worker] Fact added successfully. Current pending: {fact_count}")
                else:
                    print(f"[Memory Worker Error] Failed to add fact to Cognee server (status {resp.status_code}): {resp.text}")
                
                memory_queue.task_done()
                
            except asyncio.TimeoutError:
                # Idle timeout reached, trigger cognify if there are any un-cognified facts
                if fact_count > 0:
                    print(f"[Memory Worker] Idle for {IDLE_TIMEOUT}s. Triggering cognify for {fact_count} pending facts...")
                    resp = await asyncio.to_thread(
                        requests.post,
                        f"{base_url}/cognify",
                        timeout=300
                    )
                    if resp.status_code == 200:
                        print("[Memory Worker] Cognify completed successfully.")
                        fact_count = 0
                    else:
                        print(f"[Memory Worker Error] Cognify call failed (status {resp.status_code}): {resp.text}")
                continue
                
            # If the threshold of pending facts is met, trigger cognify immediately
            if fact_count >= COGNIFY_THRESHOLD:
                print(f"[Memory Worker] Threshold of {COGNIFY_THRESHOLD} facts met. Triggering cognify...")
                resp = await asyncio.to_thread(
                    requests.post,
                    f"{base_url}/cognify",
                    timeout=300
                )
                if resp.status_code == 200:
                    print("[Memory Worker] Cognify completed successfully.")
                    fact_count = 0
                else:
                    print(f"[Memory Worker Error] Cognify call failed (status {resp.status_code}): {resp.text}")
                    
        except Exception as e:
            print(f"[Memory Worker Error] Exception in background worker: {e}")
            await asyncio.sleep(5)  # Cooldown on general errors before retrying
