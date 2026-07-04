import sys
import subprocess
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_ROOT))

def main():
    print("================================================================================")
    print("                    S.H.A.D.O.W. v4 Launcher Script (Phase 1)                   ")
    print("================================================================================")

    # Resolve Python interpreter in venv
    venv_python = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        # Fallback to sys.executable if venv python doesn't exist
        venv_python = sys.executable

    processes = []
    try:
        # 1. Start the Wake Word Listener process
        print("[Launcher] Starting wake word listener...")
        listener = subprocess.Popen(
            [str(venv_python), str(PROJECT_ROOT / "run_listener.py")],
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )
        processes.append(listener)
        
        # 2. Start the Overlay Widget process
        print("[Launcher] Starting visual overlay UI...")
        overlay = subprocess.Popen(
            [str(venv_python), str(PROJECT_ROOT / "run_overlay.py")]
        )
        processes.append(overlay)
        
        # Wait a brief moment to let processes establish
        time.sleep(1.0)
        
        # 3. Start the Orchestrator loop (runs blocking in the foreground)
        print("[Launcher] Starting main orchestrator voice loop...")
        
        from src.orchestrator import main as orchestrator_main
        import asyncio
        asyncio.run(orchestrator_main())

    except KeyboardInterrupt:
        print("\n[Launcher] Shutdown signal received (Ctrl+C). Terminating subprocesses...")
    except Exception as e:
        print(f"\n[Launcher Error] An error occurred: {e}")
    finally:
        # Clean up all spawned subprocesses
        for proc in processes:
            if proc.poll() is None:
                print(f"[Launcher] Terminating process {proc.pid}...")
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    print(f"[Launcher] Force-killing process {proc.pid}...")
                    proc.kill()
        print("[Launcher] All subprocesses terminated. Goodbye.")

if __name__ == "__main__":
    main()
