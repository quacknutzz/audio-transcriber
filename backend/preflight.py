"""Pre-flight check: verify all pipeline dependencies are importable and compatible."""
import sys
import os

# Suppress TF warnings
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

print("Python:", sys.version)
errors = []

# 1. Core ML
try:
    import torch
    cuda_info = "CPU only"
    if torch.cuda.is_available():
        cuda_info = torch.cuda.get_device_name(0)
    print(f"  torch: {torch.__version__} | CUDA: {torch.cuda.is_available()} | Device: {cuda_info}")
except Exception as e:
    errors.append(f"torch: {e}")

# 2. torchaudio (separation)
try:
    import torchaudio
    print(f"  torchaudio: {torchaudio.__version__}")
except Exception as e:
    errors.append(f"torchaudio: {e}")

# 3. soundfile (WAV saving - used by patched demucs)
try:
    import soundfile as sf
    print(f"  soundfile: {sf.__version__}")
except Exception as e:
    errors.append(f"soundfile: {e}")

# 4. transformers (MT3 dependency)
try:
    import transformers
    print(f"  transformers: {transformers.__version__}")
    major = int(transformers.__version__.split(".")[0])
    if major >= 5:
        errors.append(f"transformers {transformers.__version__} is 5.x! mt3-infer needs 4.x")
    # Verify key classes exist
    from transformers import PreTrainedModel
    assert hasattr(PreTrainedModel, "get_head_mask"), "get_head_mask missing!"
    print("    get_head_mask: EXISTS")
    assert hasattr(PreTrainedModel, "invert_attention_mask"), "invert_attention_mask missing!"
    print("    invert_attention_mask: EXISTS")
except AssertionError as e:
    errors.append(f"transformers API: {e}")
except Exception as e:
    errors.append(f"transformers: {e}")

# 5. mt3_infer
try:
    from mt3_infer import load_model
    print("  mt3_infer: OK")
except Exception as e:
    errors.append(f"mt3_infer: {e}")

# 6. demucs
try:
    import demucs
    print(f"  demucs: {demucs.__version__}")
    # Check save_audio uses soundfile
    from demucs.audio import save_audio
    import inspect
    src = inspect.getsource(save_audio)
    if "soundfile" in src or "sf.write" in src:
        print("    save_audio: PATCHED (soundfile)")
    else:
        errors.append("demucs save_audio not patched - will fail with torchcodec!")
except Exception as e:
    errors.append(f"demucs: {e}")

# 7. basic-pitch (fallback)
try:
    from basic_pitch.inference import predict
    print("  basic_pitch: OK")
except Exception as e:
    errors.append(f"basic_pitch: {e}")

# 8. torchcrepe (vocals)
try:
    import torchcrepe
    print("  torchcrepe: OK")
except Exception as e:
    errors.append(f"torchcrepe: {e}")

# 9. librosa (audio analysis)
try:
    import librosa
    print(f"  librosa: {librosa.__version__}")
except Exception as e:
    errors.append(f"librosa: {e}")

# 10. music21 (sheet music)
try:
    import music21
    print(f"  music21: {music21.__version__}")
except Exception as e:
    errors.append(f"music21: {e}")

# 11. mido/pretty_midi
try:
    import mido, pretty_midi
    print("  mido + pretty_midi: OK")
except Exception as e:
    errors.append(f"mido/pretty_midi: {e}")

# 12. Quick app import test
try:
    sys.path.insert(0, "backend")
    from services.separation import SeparationService
    from services.transcription import TranscriptionService
    from services.music_processing import MusicProcessingService
    print("  App services: ALL IMPORTED OK")
except Exception as e:
    errors.append(f"App services: {e}")

print()
if errors:
    print(f"ISSUES FOUND ({len(errors)}):")
    for e in errors:
        print(f"  X {e}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED!")
    sys.exit(0)
