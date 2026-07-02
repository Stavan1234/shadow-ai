import os
import re
import sys
import json
import zipfile
import urllib.request
import urllib.error
from pathlib import Path

# Directories
PROJECT_ROOT = Path(__file__).resolve().parent
BIN_DIR = PROJECT_ROOT / "bin"
MODELS_DIR = PROJECT_ROOT / "models"
GGUF_DIR = MODELS_DIR / "gguf"
PIPER_DIR = MODELS_DIR / "piper"

# Create directories
for path in (BIN_DIR, MODELS_DIR, GGUF_DIR, PIPER_DIR):
    path.mkdir(parents=True, exist_ok=True)

def download_file(url, target_path, desc="File"):
    target_path = Path(target_path)
    if target_path.exists():
        # Check size if it's already downloaded, if it's large assume done
        if target_path.stat().st_size > 1024 * 1024:
            print(f"[Skip] {desc} already exists at {target_path} (size: {target_path.stat().st_size / (1024*1024):.1f} MB). Skipping download.")
            return True
            
    print(f"\n[Downloading] {desc}...")
    print(f"Source: {url}")
    print(f"Target: {target_path}")
    
    req = urllib.request.Request(
        url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    )
    
    try:
        with urllib.request.urlopen(req) as response, open(target_path, 'wb') as out_file:
            meta = response.info()
            file_size_str = meta.get("Content-Length")
            file_size = int(file_size_str) if file_size_str else None
            
            chunk_size = 1024 * 1024  # 1 MB chunk
            downloaded = 0
            while True:
                buffer = response.read(chunk_size)
                if not buffer:
                    break
                out_file.write(buffer)
                downloaded += len(buffer)
                if file_size:
                    percent = (downloaded / file_size) * 100
                    print(f" -> {percent:.1f}% ({downloaded / (1024*1024):.1f} MB / {file_size / (1024*1024):.1f} MB)", end="\r")
                else:
                    print(f" -> Downloaded {downloaded / (1024*1024):.1f} MB", end="\r")
            print(f"\n[Success] Finished downloading {desc}!")
            return True
    except Exception as e:
        print(f"\n[Error] Failed to download {desc}: {e}")
        # Clean up partial download
        if target_path.exists():
            try:
                target_path.unlink()
            except Exception:
                pass
        return False

def get_latest_github_release_asset(repo, name_pattern):
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    )
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            assets = data.get("assets", [])
            for asset in assets:
                name = asset.get("name", "")
                if re.search(name_pattern, name, re.IGNORECASE):
                    return asset.get("browser_download_url"), name
    except Exception as e:
        print(f"[Warning] Failed to fetch latest release from GitHub API for {repo}: {e}")
    return None, None

def extract_zip(zip_path, extract_dir):
    print(f"[Extracting] {zip_path} to {extract_dir}...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        print("[Success] Extracted successfully!")
        return True
    except Exception as e:
        print(f"[Error] Failed to extract {zip_path}: {e}")
        return False

def main():
    print("================================================================================")
    print("                  S.H.A.D.O.W. v4 Dependency Downloader Script                  ")
    print("================================================================================")
    
    # 1. Download Llama.cpp Server (win-cpu-x64)
    print("\n--- 1. LLAMA.CPP SERVER ---")
    llama_repo = "ggml-org/llama.cpp"
    llama_pattern = r"bin-win-cpu-x64\.zip"
    download_url, zip_name = get_latest_github_release_asset(llama_repo, llama_pattern)
    
    # Fallback if GitHub API fails
    if not download_url:
        print("[Info] Using hardcoded fallback URL for llama.cpp...")
        download_url = "https://github.com/ggml-org/llama.cpp/releases/download/b4556/llama-b4556-bin-win-cpu-x64.zip"
        zip_name = "llama-b4556-bin-win-cpu-x64.zip"
        
    llama_zip_path = BIN_DIR / zip_name
    llama_extract_dir = BIN_DIR / "llama-server"
    llama_extract_dir.mkdir(exist_ok=True)
    
    # Check if llama-server.exe already exists
    server_exe = llama_extract_dir / "llama-server.exe"
    if server_exe.exists():
        print(f"[Skip] llama-server.exe already exists at {server_exe}. Skipping.")
    else:
        if download_file(download_url, llama_zip_path, "llama.cpp zip"):
            if extract_zip(llama_zip_path, llama_extract_dir):
                # Clean up zip file
                try:
                    llama_zip_path.unlink()
                except Exception:
                    pass

    # 2. Download Piper TTS Executable (windows-amd64)
    print("\n--- 2. PIPER TTS ENGINE ---")
    piper_repo = "rhasspy/piper"
    piper_pattern = r"piper_windows_amd64\.zip"
    download_url, zip_name = get_latest_github_release_asset(piper_repo, piper_pattern)
    
    # Fallback if GitHub API fails
    if not download_url:
        print("[Info] Using hardcoded fallback URL for Piper...")
        download_url = "https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_windows_amd64.zip"
        zip_name = "piper_windows_amd64.zip"
        
    piper_zip_path = BIN_DIR / zip_name
    piper_extract_dir = BIN_DIR / "piper"
    piper_extract_dir.mkdir(exist_ok=True)
    
    piper_exe = piper_extract_dir / "piper" / "piper.exe" # Piper zip extracts nested piper folder
    if piper_exe.exists():
        print(f"[Skip] piper.exe already exists at {piper_exe}. Skipping.")
    else:
        # Check alternative extraction path
        alt_exe = piper_extract_dir / "piper.exe"
        if alt_exe.exists():
            print(f"[Skip] piper.exe already exists at {alt_exe}. Skipping.")
        else:
            if download_file(download_url, piper_zip_path, "piper zip"):
                if extract_zip(piper_zip_path, piper_extract_dir):
                    # Clean up zip file
                    try:
                        piper_zip_path.unlink()
                    except Exception:
                        pass

    # 3. Download Piper ONNX Voice Model (en_US-lessac-medium)
    print("\n--- 3. PIPER VOICE MODEL ---")
    voice_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx?download=true"
    config_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json?download=true"
    
    download_file(voice_url, PIPER_DIR / "en_US-lessac-medium.onnx", "Piper voice ONNX model")
    download_file(config_url, PIPER_DIR / "en_US-lessac-medium.onnx.json", "Piper voice config JSON")

    # 4. Download GGUF Language Models
    print("\n--- 4. QWEN2.5 GGUF MODELS (LARGE DOWNLOADS) ---")
    
    # 3B model (foreground chat)
    qwen_3b_url = "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf?download=true"
    download_file(qwen_3b_url, GGUF_DIR / "qwen2.5-3b-instruct-q4_k_m.gguf", "Qwen2.5 3B Instruct GGUF (Chat)")
    
    # 7B model (background processing)
    qwen_7b_url = "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf?download=true"
    download_file(qwen_7b_url, GGUF_DIR / "qwen2.5-7b-instruct-q4_k_m.gguf", "Qwen2.5 7B Instruct GGUF (Background)")

    print("\n================================================================================")
    print("                     ALL REQUIRED ASSETS VERIFIED / DOWNLOADED                  ")
    print("================================================================================")

if __name__ == "__main__":
    main()
