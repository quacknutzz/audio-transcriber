"""
Standalone MT3 worker module for multiprocessing.

This module defines top-level functions (required for pickling by ProcessPoolExecutor).
Each worker process loads its own MT3 model into GPU VRAM independently,
enabling true parallel GPU inference across 2 physical OS processes.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Each worker process holds its own cached model in its memory space
_cached_model = None


def _get_model():
    """Load or return the cached MT3 model for this worker process."""
    global _cached_model
    if _cached_model is None:
        from mt3_infer import load_model as mt3_load_model
        logger.info(f"[Worker PID {__import__('os').getpid()}] Loading MT3 model into VRAM...")
        _cached_model = mt3_load_model(
            model="mr_mt3",
            device="auto",
            auto_download=True
        )
        logger.info(f"[Worker PID {__import__('os').getpid()}] MT3 model ready.")
    return _cached_model


def transcribe_stem(audio_path_str: str, output_midi_path_str: str, instrument_name: str) -> str:
    """
    Top-level function that can be pickled and sent to a ProcessPoolExecutor worker.
    Loads audio, runs MT3 inference, saves MIDI, and returns the output path as a string.
    """
    import os
    pid = os.getpid()
    
    try:
        import librosa
        
        audio_path = Path(audio_path_str)
        output_midi_path = Path(output_midi_path_str)
        output_midi_path.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"[Worker PID {pid}] Loading audio for {instrument_name}: {audio_path}")
        y_np, sr = librosa.load(str(audio_path), sr=16000)
        
        model = _get_model()
        
        print(f"[Worker PID {pid}] Running MT3 inference for {instrument_name}...")
        midi_data = model.transcribe(y_np, sr=16000)
        
        midi_data.save(str(output_midi_path))
        print(f"[Worker PID {pid}] MT3 complete for {instrument_name}: {output_midi_path}")
        
        return str(output_midi_path)
        
    except Exception as e:
        import traceback
        print(f"[Worker PID {pid}] MT3 FAILED for {instrument_name}: {e}\n{traceback.format_exc()}")
        # Return empty string to signal failure - caller will fall back to Basic Pitch
        return ""
