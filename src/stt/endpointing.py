import os
import wave
import collections
import sounddevice as sd
import webrtcvad

def record_until_silence(
    out_path="data/temp_input.wav", 
    sample_rate=16000, 
    frame_ms=30, 
    silence_hangover_ms=1200, 
    max_duration_s=15
) -> str:
    """
    Records audio from the microphone using webrtcvad to detect silence.
    Stops recording after a continuous period of silence once speech has started,
    or if no speech is heard at all in the first 4 seconds.
    Saves the final clip as a standard WAV file.
    """
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    
    # Initialize VAD (mode 2: good balance for home/office rooms)
    vad = webrtcvad.Vad(2)
    
    channels = 1
    bytes_per_sample = 2  # 16-bit PCM = 2 bytes
    frame_samples = int(sample_rate * frame_ms / 1000)
    frame_bytes = frame_samples * bytes_per_sample
    
    print("[VAD] Listening...")
    audio_frames = []
    
    # RawInputStream yields PCM bytes directly without float conversions
    stream = sd.RawInputStream(
        samplerate=sample_rate, 
        channels=channels, 
        dtype='int16', 
        blocksize=frame_samples
    )
    
    silence_run_ms = 0
    total_ms = 0
    started_speech = False
    
    with stream:
        while True:
            # Read frame PCM data
            frame, overflowed = stream.read(frame_samples)
            if not frame:
                break
                
            frame_bytes_data = bytes(frame)
            audio_frames.append(frame_bytes_data)
            total_ms += frame_ms
            
            # Check voice activity on 16-bit mono 16kHz audio frame
            is_speech = vad.is_speech(frame_bytes_data, sample_rate)
            
            if is_speech:
                if not started_speech:
                    print("[VAD] Voice detected...")
                    started_speech = True
                silence_run_ms = 0
            else:
                if started_speech:
                    silence_run_ms += frame_ms
            
            # Silence hangover check
            if started_speech and silence_run_ms >= silence_hangover_ms:
                print(f"[VAD] Stop trigger: continuous silence for {silence_run_ms}ms.")
                break
                
            # Timeout checks
            if (total_ms / 1000.0) >= max_duration_s:
                print("[VAD] Stop trigger: max duration reached.")
                break
                
            if not started_speech and (total_ms / 1000.0) >= 4.0:
                print("[VAD] Stop trigger: no speech detected in first 4 seconds.")
                break
                
    # Save frames to WAV
    with wave.open(out_path, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(bytes_per_sample)
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(audio_frames))
        
    return out_path
