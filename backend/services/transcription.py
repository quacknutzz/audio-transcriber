from pathlib import Path
import logging
from basic_pitch.inference import predict_and_save
from basic_pitch import ICASSP_2022_MODEL_PATH
import librosa
import numpy as np
import soundfile as sf

class TranscriptionService:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        self.mt3_model = None

    async def transcribe_melody(self, audio_path: Path, output_name: str, instrument_name: str = "other") -> Path:
        """
        Transcribes audio to MIDI using SOTA MT3 model (Instruments) or Basic Pitch (Vocals).
        """
        self.logger.info(f"Transcribing {instrument_name}: {audio_path}")
        
        # 1. Vocals: Use Basic Pitch (fast, accurate for monophonic melody)
        if instrument_name.lower() == "vocals":
             return await self._transcribe_basic_pitch(audio_path, output_name, instrument_name)

        # 2. Instruments: Use Google MT3 (Multi-Task Multitrack)
        # This covers Piano, Guitar, Bass, Other
        return await self._transcribe_mt3(audio_path, output_name, instrument_name)

    async def _transcribe_mt3(self, audio_path: Path, output_name: str, instrument_name: str) -> Path:
        """
        Uses mt3-infer to transcribe audio.
        """
        output_midi_path = self.output_dir / f"{output_name}_mt3.mid"
        self.logger.info(f"Using MT3 for {instrument_name}...")
        
        try:
            import torchaudio
            from mt3_infer import load_model as mt3_load_model
            
            # Load Audio (Torchaudio uses fast native C++ wrappers)
            y_tensor, sr = torchaudio.load(str(audio_path))
            
            # Downsample to exactly 16000Hz dynamically
            if sr != 16000:
                resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=16000)
                y_tensor = resampler(y_tensor)
                
            # Flatten to 1D mono (MT3 expects a flat 1D numpy array)
            if y_tensor.shape[0] > 1:
                y_tensor = y_tensor.mean(dim=0, keepdim=True)
            y_np = y_tensor.squeeze(0).numpy()
            
            # Cache the model to globally resident RAM/VRAM to prevent 15s+ reload on every stem
            if self.mt3_model is None:
                self.logger.info("Initializing MT3 model weights to memory caching (this happens once)...")
                self.mt3_model = mt3_load_model(
                    model="mr_mt3",
                    device="auto",
                    auto_download=True
                )
            
            # Transcribe from the globally cached model
            self.logger.info("Running MT3 inference...")
            midi_data = self.mt3_model.transcribe(y_np, sr=16000)
            
            # Save MIDI
            midi_data.save(str(output_midi_path))
            
            self.logger.info(f"MT3 success: {output_midi_path}")
            return output_midi_path

        except Exception as e:
            import traceback
            self.logger.error(f"MT3 Transcription failed: {e}\n{traceback.format_exc()}")
            # Fallback to Basic Pitch?
            self.logger.warning("Falling back to Basic Pitch...")
            return await self._transcribe_basic_pitch(audio_path, output_name, instrument_name)

    async def _transcribe_basic_pitch(self, audio_path: Path, output_name: str, instrument_name: str) -> Path:
        """
        Fallback to Basic Pitch if MT3 fails or for specific tuning.
        """
        output_midi_path = self.output_dir / f"{output_name}_basic_pitch.mid"
        try:
            # Default parameters (tuned for general use)
            onset_threshold = 0.5
            frame_threshold = 0.3
            minimum_note_length = 58.0
            minimum_frequency = None
            maximum_frequency = None
            
            # Instrument-specific tuning (legacy)
            if instrument_name.lower() == "bass":
                onset_threshold = 0.6
                minimum_frequency = 40.0
                maximum_frequency = 400.0
            
            expected_output = self.output_dir / f"{audio_path.stem}_basic_pitch.mid"
            if expected_output.exists():
                self.logger.info(f"Removing existing Basic Pitch output to prevent collision: {expected_output}")
                expected_output.unlink(missing_ok=True)
                
            predict_and_save(
                audio_path_list=[str(audio_path)],
                output_directory=str(self.output_dir),
                save_midi=True,
                sonify_midi=False,
                save_model_outputs=False,
                save_notes=False,
                model_or_model_path=ICASSP_2022_MODEL_PATH.parent / "nmp.onnx",
                onset_threshold=onset_threshold,
                frame_threshold=frame_threshold,
                minimum_note_length=minimum_note_length,
                minimum_frequency=minimum_frequency,
                maximum_frequency=maximum_frequency
            )
            
            if expected_output.exists():
                if expected_output != output_midi_path:
                    try:
                        expected_output.replace(output_midi_path)
                    except OSError:
                        import shutil
                        shutil.copy2(expected_output, output_midi_path)
                        expected_output.unlink()
                return output_midi_path
            else:
                 raise Exception("Basic Pitch did not generate the expected MIDI file.")

        except Exception as e:
            raise e

    def _download_file(self, url: str, dest_path: Path):
        import urllib.request
        from tqdm import tqdm
        
        class DownloadProgressBar(tqdm):
            def update_to(self, b=1, bsize=1, tsize=None):
                if tsize is not None:
                    self.total = tsize
                self.update(b * bsize - self.n)

        self.logger.info(f"Downloading model from {url} to {dest_path}")
        with DownloadProgressBar(unit='B', unit_scale=True, miniters=1, desc=url.split('/')[-1]) as t:
            urllib.request.urlretrieve(url, filename=dest_path, reporthook=t.update_to)

    async def _transcribe_piano(self, audio_path: Path, output_name: str) -> Path:
        """
        Specialized transcription for Piano using ByteDance's piano_transcription_inference.
        """
        output_midi_path = self.output_dir / f"{output_name}_piano.mid"
        self.logger.info(f"Using AI Piano Model for: {audio_path}")
        
        try:
            # Lazy import to avoid heavy load if not needed
            from piano_transcription_inference import PianoTranscription, sample_rate, load_audio
            import torch
            import os
            
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            self.logger.info(f"Piano Transcription Device: {device}")
            
            # Ensure model is downloaded manually to avoid wget
            home_dir = Path.home()
            model_dir = home_dir / "piano_transcription_inference_data"
            model_dir.mkdir(parents=True, exist_ok=True)
            checkpoint_path = model_dir / "note_F1=0.9677_pedal_F1=0.9186.pth"
            
            if not checkpoint_path.exists() or checkpoint_path.stat().st_size < 1.6e8:
                zenodo_url = 'https://zenodo.org/record/4034264/files/CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1'
                self._download_file(zenodo_url, checkpoint_path)
            
            # Load audio using librosa directly to avoid ffmpeg dependency
            import librosa
            import numpy as np
            audio, _ = librosa.load(str(audio_path), sr=sample_rate, mono=True)
            
            # Transcribe
            transcriptor = PianoTranscription(device=device, checkpoint_path=str(checkpoint_path))
            transcriptor.transcribe(audio, str(output_midi_path))
            
            return output_midi_path
            
        except Exception as e:
            self.logger.error(f"Piano transcription failed: {e}")
            raise e

    async def _transcribe_monophonic(self, audio_path: Path, output_name: str, instrument_name: str) -> Path:
        """
        Uses TorchCrepe for high-quality monophonic pitch tracking (Vocals/Bass).
        Converts detailed pitch curves into discrete MIDI notes.
        """
        output_midi_path = self.output_dir / f"{output_name}_crepe.mid"
        self.logger.info(f"Using TorchCrepe for {instrument_name}: {audio_path}")
        
        try:
            import torchcrepe
            import torch
            import numpy as np
            import librosa
            from music21 import stream, note, tempo, meter
            
            # Load audio
            # sr=16000 is standard for Crepe
            sr = 16000
            audio, _ = librosa.load(str(audio_path), sr=sr, mono=True)
            
            # Move to GPU if available
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            self.logger.info(f"Crepe Device: {device}")
            
            # Predict pitch
            # hop_length=160 (10ms at 16k)
            hop_length = 160
            fmin = 50  # Bass low E is ~41Hz
            fmax = 2000 # High soprano C is ~1000Hz (2k safe)
            model = 'full'
            
            # Provide batch_size to avoid OOM on GPU
            batch_size = 2048
            
            audio_tensor = torch.tensor(audio).unsqueeze(0).to(device)
            
            # get pitch and confidence
            pitch, confidence = torchcrepe.predict(
                audio_tensor,
                sr,
                hop_length,
                fmin,
                fmax,
                model,
                batch_size=batch_size,
                device=device,
                return_periodicity=True
            )
            
            pitch = pitch.squeeze().cpu().numpy()
            confidence = confidence.squeeze().cpu().numpy()
            
            # --- Convert Frame-Level Pitch to MIDI Notes ---
            # Heuristic:
            # 1. Filter by confidence (ignore noise)
            # 2. Group consecutive frames of similar pitch (within semitone)
            # 3. Create Note if duration > threshold
            
            conf_thresh = 0.6 if instrument_name == "vocals" else 0.7
            
            # Create Music21 stream
            s = stream.Score()
            p = stream.Part()
            p.id = 'P1'
            p.partName = instrument_name
            s.insert(0, p)
            
            # 10ms per frame
            seconds_per_frame = hop_length / sr
            
            current_midi = None
            start_frame = 0
            
            # Iterate through frames
            for i, (f, c) in enumerate(zip(pitch, confidence)):
                if c < conf_thresh or np.isnan(f):
                    # Silence/Noise
                    if current_midi is not None:
                        # End previous note
                        duration_sec = (i - start_frame) * seconds_per_frame
                        if duration_sec >= 0.05: # Min 50ms note
                            n = note.Note(current_midi)
                            n.quarterLength = duration_sec * 2 # Approx mapping? No, need tempo.
                            # Standardizing: Let's assume 120bpm for "seconds to quarterLength" map
                            # 120bpm = 2 beats/sec = 0.5 sec/beat (quarter note)
                            # So quarterLength = duration_sec / 0.5 = duration_sec * 2
                            # This is arbitrary but valid for XML output which defines its own time
                            # actually music21 expects quarterLength.
                            n.quarterLength = duration_sec * (120 / 60)
                            p.append(n)
                            
                        current_midi = None
                    continue
                
                # We have a pitch
                # Convert Hz to MIDI note
                # 69 + 12 * log2(f / 440)
                mid_val = 69 + 12 * np.log2(f / 440)
                mid_round = int(round(mid_val))
                
                if current_midi is None:
                    # New note start
                    current_midi = mid_round
                    start_frame = i
                else:
                    # Continuation check
                    if mid_round != current_midi:
                        # Pitch changed -> End old note, start new
                        duration_sec = (i - start_frame) * seconds_per_frame
                        if duration_sec >= 0.05:
                            n = note.Note(current_midi)
                            n.quarterLength = duration_sec * 2
                            p.append(n)
                        
                        current_midi = mid_round
                        start_frame = i
                        
            # End final note
            if current_midi is not None:
                duration_sec = (len(pitch) - start_frame) * seconds_per_frame
                if duration_sec >= 0.05:
                    n = note.Note(current_midi)
                    n.quarterLength = duration_sec * 2
                    p.append(n)

            # Write MIDI
            p.write('midi', fp=str(output_midi_path))
            return output_midi_path
            
        except Exception as e:
            self.logger.error(f"Crepe transcription failed: {e}")
            raise e

    async def _transcribe_drums(self, audio_path: Path, output_name: str) -> Path:
        """
        Uses Librosa onset detection for Drums.
        """
        output_midi_path = self.output_dir / f"{output_name}_drums.mid"
        self.logger.info(f"Using Librosa Onset for Drums: {audio_path}")
        
        try:
            import librosa
            import numpy as np
            from music21 import stream, note, tempo, meter
            
            # Load audio
            y, sr = librosa.load(str(audio_path), sr=None)
            
            # Detect Onsets (Backtracking for precision)
            # This finds the start of the attack
            onset_frames = librosa.onset.onset_detect(y=y, sr=sr, backtrack=True)
            onset_times = librosa.frames_to_time(onset_frames, sr=sr)
            
            # Estimate beats for tempo (optional, but helps struct formatting if we cared)
            tempo_est, _ = librosa.beat.beat_track(y=y, sr=sr)
            
            # Create Music21 stream
            s = stream.Score()
            p = stream.Part()
            p.id = 'P1'
            p.partName = "Drums"
            s.insert(0, p)
            
            # Map events to MIDI
            # For now, put everything on a generic "Snare" or "Kick" pitch (e.g., C3 = 48)
            # Or use Unpitched percussion if possible?
            # Standard MIDI Drum Map: Kick=36 (C2), Snare=38 (D2), HiHat=42 (F#2)
            # Since we can't classify, let's pick a neutral generic 'hit' like Snare (38) or just C3.
            # Let's use 38 (Snare) as it's common.
            
            # We need to calculate durations. Since drums are impulsive, duration doesn't matter much.
            # We'll set a short 16th note duration.
            
            # 120 BPM reference for duration calc
            # 16th note = 0.25 quarter length = 0.125 seconds at 120bpm
            
            for t in onset_times:
                # We need to place it in the timeline.
                # Music21 works in quarterLengths.
                # We need an absolute timeline.
                # Simplest is to assume 120bpm for the XML grid later.
                
                # t is seconds.
                # quarter_offset = t * (120 / 60) = t * 2
                
                offset = t * 2.0
                
                n = note.Note(38) # D2? No 38 is typically snare in GM Percussion map (Channel 10)
                # But here we are making a normal part.
                # If we want it to look like drums, we might want to set the channel?
                # For now, just notes.
                n.quarterLength = 0.25 
                p.insert(offset, n)
                
            # Write MIDI
            p.write('midi', fp=str(output_midi_path))
            return output_midi_path

        except Exception as e:
            self.logger.error(f"Drum transcription failed: {e}")
            raise e
            
            # 1. Separate harmonic and percussive components
            y_harmonic, y_percussive = librosa.effects.hpss(y)
            
            # 2. Onset detection (general)
            onset_env = librosa.onset.onset_strength(y=y_percussive, sr=sr)
            onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, units='time')
            
            # 3. Frequency-based classification (Simple MVP)
            # We will look at the spectral centroid of the audio at each onset to guess the instrument.
            # Low centroid -> Kick
            # Mid centroid -> Snare
            # High centroid -> Hi-Hat
            
            import pretty_midi
            
            # Create a PrettyMIDI object
            pm = pretty_midi.PrettyMIDI()
            # Create an Instrument instance for a drum kit
            # is_drum=True is important for MIDI renderers to use drum sounds
            drum_inst = pretty_midi.Instrument(program=0, is_drum=True, name="Drums")
            
            # Define approximate frequency thresholds (tuned heuristically)
            # These are very rough and brittle, but serve as an MVP without a trained model.
            
            for onset_time in onsets:
                # Extract a small window around the onset
                start_sample = int(onset_time * sr)
                end_sample = min(int((onset_time + 0.1) * sr), len(y))
                if start_sample >= end_sample:
                    continue
                
                segment = y[start_sample:end_sample]
                
                # Calculate Spectral Centroid
                centroid = librosa.feature.spectral_centroid(y=segment, sr=sr)[0].mean()
                
                midi_note = None
                velocity = 100
                
                if centroid < 1500:
                    midi_note = 36 # Kick
                elif 1500 <= centroid < 3500:
                    midi_note = 38 # Snare
                elif centroid >= 3500:
                    midi_note = 42 # Closed Hi-Hat
                
                if midi_note:
                    # Create a Note instance
                    note = pretty_midi.Note(
                        velocity=velocity,
                        pitch=midi_note,
                        start=onset_time,
                        end=onset_time + 0.1
                    )
                    drum_inst.notes.append(note)
            
            pm.instruments.append(drum_inst)
            pm.write(str(output_midi_path))
            
            return output_midi_path

        except Exception as e:
            self.logger.error(f"Drum transcription failed: {e}")
            raise e
