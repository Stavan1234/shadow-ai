import os
from faster_whisper import WhisperModel

# Initialize WhisperModel once on import
# We use tiny.en for low-latency CPU inference under INT8 compute quantization
stt_model = None

def get_stt_model():
    global stt_model
    if stt_model is None:
        print("[STT] Loading Whisper model (tiny.en, CPU, INT8)...")
        # Load local model or download if not already cached
        stt_model = WhisperModel(
            model_size_or_path="tiny.en", 
            device="cpu", 
            compute_type="int8"
        )
    return stt_model

def transcribe(audio_path: str) -> str:
    """
    Transcribe the given WAV audio file using faster-whisper.
    """
    if not os.path.exists(audio_path):
        print(f"[STT Error] Audio file not found at {audio_path}")
        return ""
        
    model = get_stt_model()
    
    # beam_size=1 is faster and sufficient for English commands
    # vad_filter=True filters out silences at start/end
    segments, info = model.transcribe(audio_path, beam_size=1, vad_filter=True)
    
    text = " ".join(segment.text for segment in segments).strip()
    return text
