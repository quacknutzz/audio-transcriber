from pathlib import Path
import logging
import gc
import torch
import librosa
import numpy as np
import soundfile as sf
from basic_pitch.inference import predict_and_save
from basic_pitch import ICASSP_2022_MODEL_PATH

class TranscriptionService:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)

    async def transcribe_instrument(self, audio_path: Path, output_name: str, instrument_name: str = "other") -> Path:
        """
        Routes the isolated audio stem to its dedicated domain-specific SOTA transcriber.
        - Piano/Keys: ByteDance Classical/Polyphonic CRNN (trained on MAESTRO, 96.7% note F1)
        - Vocals: Basic Pitch with high vocal onset sensitivity
        - Bass: Basic Pitch with strict bass bandpass (40Hz - 400Hz) to prevent drum bleed
        - Guitar / Other: Basic Pitch polyphonic ONNX model
        - Drums: Rhythmic transient onset detector mapped to GM percussion MIDI
        """
        self.logger.info(f"Transcribing {instrument_name}: {audio_path}")
        inst = instrument_name.lower()
        
        try:
            if inst in ["piano", "keys"]:
                midi_path = await self._transcribe_piano(audio_path, output_name)
            elif inst == "drums":
                midi_path = await self._transcribe_drums(audio_path, output_name)
            elif inst == "vocals":
                midi_path = await self._transcribe_basic_pitch(audio_path, output_name, instrument_name="vocals")
            elif inst == "bass":
                midi_path = await self._transcribe_basic_pitch(audio_path, output_name, instrument_name="bass")
            else:
                # Guitar, other, synths, etc.
                midi_path = await self._transcribe_basic_pitch(audio_path, output_name, instrument_name=inst)
                
            return midi_path

        except Exception as e:
            self.logger.error(f"Primary transcription failed for {instrument_name} ({e}). Falling back to Basic Pitch...")
            return await self._transcribe_basic_pitch(audio_path, output_name, instrument_name=inst)
        finally:
            # Crucial for 6GB VRAM safety: immediately purge PyTorch CUDA cache and collect garbage
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    async def transcribe_melody(self, audio_path: Path, output_name: str, instrument_name: str = "other") -> Path:
        """Alias for backwards compatibility."""
        return await self.transcribe_instrument(audio_path, output_name, instrument_name)

    async def _transcribe_piano(self, audio_path: Path, output_name: str) -> Path:
        """
        Specialized transcription for Piano using ByteDance's piano_transcription_inference.
        Uses MAESTRO CRNN weights with pedal detection.
        """
        output_midi_path = self.output_dir / f"{output_name}_piano.mid"
        self.logger.info(f"Running ByteDance Piano Model for: {audio_path}")
        
        from piano_transcription_inference import PianoTranscription, sample_rate
        
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        home_dir = Path.home()
        model_dir = home_dir / "piano_transcription_inference_data"
        model_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = model_dir / "note_F1=0.9677_pedal_F1=0.9186.pth"
        
        if not checkpoint_path.exists() or checkpoint_path.stat().st_size < 1.6e8:
            zenodo_url = 'https://zenodo.org/record/4034264/files/CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1'
            self._download_file(zenodo_url, checkpoint_path)
        
        # Load audio using librosa directly and percentile-normalize so quiet Demucs piano stems are detected accurately
        audio, _ = librosa.load(str(audio_path), sr=sample_rate, mono=True)
        p995 = float(np.percentile(np.abs(audio), 99.5)) if len(audio) > 0 else 0.0
        if p995 > 1e-6:
            audio = np.clip((audio / p995) * 0.65, -0.95, 0.95)
        
        transcriptor = PianoTranscription(device=device, checkpoint_path=str(checkpoint_path))
        transcriptor.transcribe(audio, str(output_midi_path))
        del transcriptor

        # Clean any low-energy bleed notes and verify note count & coverage; fallback to Basic Pitch if sparse
        self._clean_and_filter_midi(output_midi_path, audio_path, "piano")
        import pretty_midi
        pm_check = pretty_midi.PrettyMIDI(str(output_midi_path))
        all_p_notes = [n for i in pm_check.instruments for n in i.notes]
        note_count = len(all_p_notes)
        active_windows = len({int(n.start // 2.0) for n in all_p_notes})
        if note_count < 80 or active_windows < 15:
            self.logger.info(f"ByteDance Piano model found only {note_count} notes across {active_windows} windows; falling back to Basic Pitch.")
            return await self._transcribe_basic_pitch(audio_path, output_name, instrument_name="piano")

        return output_midi_path

    async def _transcribe_basic_pitch(self, audio_path: Path, output_name: str, instrument_name: str = "other") -> Path:
        """
        Fast, lightweight, high-accuracy neural transcription from Spotify.
        Preserves exact start/end note timestamps.
        """
        output_midi_path = self.output_dir / f"{output_name}_basic_pitch.mid"
        
        onset_threshold = 0.55
        frame_threshold = 0.35
        minimum_note_length = 65.0
        minimum_frequency = 80.0
        maximum_frequency = 1046.5
        
        inst = instrument_name.lower()
        if inst == "bass":
            # Filter to bass fundamental register only (40Hz to 350Hz) to prevent drum/bleed overlap
            onset_threshold = 0.6
            frame_threshold = 0.38
            minimum_frequency = 40.0
            maximum_frequency = 350.0
            minimum_note_length = 80.0
        elif inst == "vocals":
            # Constrain to human vocal frequency range (C3: ~130Hz to C6: ~1100Hz)
            onset_threshold = 0.55
            frame_threshold = 0.35
            minimum_frequency = 130.0
            maximum_frequency = 1100.0
            minimum_note_length = 70.0
        elif inst == "guitar":
            # Constrain to standard guitar fundamental & chord register (E2: ~82Hz to A5: ~880Hz)
            onset_threshold = 0.52
            frame_threshold = 0.33
            minimum_frequency = 80.0
            maximum_frequency = 880.0
            minimum_note_length = 65.0
        elif inst == "other":
            # Constrain to violin/fiddle/strings/synth lead register (>= 190Hz = G3) to reject low guitar body bleed
            onset_threshold = 0.55
            frame_threshold = 0.35
            minimum_frequency = 190.0
            maximum_frequency = 1175.0
            minimum_note_length = 75.0
        elif inst in ["piano", "keys"]:
            onset_threshold = 0.48
            frame_threshold = 0.30
            minimum_frequency = 65.0
            maximum_frequency = 1046.5
            minimum_note_length = 65.0

        # Percentile-normalize quiet Demucs stems (e.g. piano.wav) into a temporary WAV so Basic Pitch has optimal gain
        # even if a single transient spike exists in the stem
        target_audio_path = audio_path
        temp_norm_path = None
        try:
            y_bp, sr_bp = sf.read(str(audio_path))
            abs_y = np.abs(y_bp)
            peak_bp = float(np.max(abs_y)) if len(y_bp) > 0 else 0.0
            p995_bp = float(np.percentile(abs_y, 99.5)) if len(y_bp) > 0 else 0.0
            if 1e-5 < peak_bp < 0.25 and p995_bp > 1e-6:
                temp_norm_path = self.output_dir / f"_norm_{audio_path.stem}.wav"
                norm_y = np.clip((y_bp / p995_bp) * 0.65, -0.95, 0.95)
                sf.write(str(temp_norm_path), norm_y, sr_bp)
                target_audio_path = temp_norm_path
        except Exception:
            target_audio_path = audio_path
        
        expected_output = self.output_dir / f"{target_audio_path.stem}_basic_pitch.mid"
        if expected_output.exists():
            expected_output.unlink(missing_ok=True)
            
        try:
            predict_and_save(
                audio_path_list=[str(target_audio_path)],
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
        finally:
            if temp_norm_path and temp_norm_path.exists():
                temp_norm_path.unlink(missing_ok=True)
        
        if expected_output.exists():
            if expected_output != output_midi_path:
                try:
                    expected_output.replace(output_midi_path)
                except OSError:
                    import shutil
                    shutil.copy2(expected_output, output_midi_path)
                    expected_output.unlink(missing_ok=True)
            
            # Post-transcription acoustic energy gating and overtone cleanup
            self._clean_and_filter_midi(output_midi_path, audio_path, instrument_name)
            return output_midi_path
        else:
            raise RuntimeError(f"Basic Pitch failed to create {expected_output}")

    def _clean_and_filter_midi(self, midi_path: Path, audio_path: Path, instrument_name: str):
        """
        Cleans and post-processes transcribed MIDI:
        1. Energy gating: Drops phantom notes that occur during silence or stem bleed (e.g. song intros).
        2. Monophonizing: For monophonic lines (vocals and bass), removes simultaneous overtone harmonics
           and trims overlapping note boundaries so the melody line remains clean single-voice.
        """
        import pretty_midi
        inst = instrument_name.lower()
        
        try:
            pm = pretty_midi.PrettyMIDI(str(midi_path))
            if not pm.instruments:
                return
            
            # Load stem audio for RMS energy gating (use outlier-resistant frame RMS so 1-sec transient spikes don't mute the track)
            y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
            global_rms = float(np.sqrt(np.mean(y**2))) if len(y) > 0 else 0.0
            fr_rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0] if len(y) > 0 else np.array([0.0])
            active_fr = fr_rms[fr_rms > 1e-6]
            p75_rms = float(np.percentile(active_fr, 75)) if len(active_fr) > 0 else global_rms
            robust_rms = min(global_rms, p75_rms)
            
            # Stem-adaptive thresholds so quiet piano/other stems are preserved while silence/bleed is gated
            base_rms = 0.003 if inst == "vocals" else (0.004 if inst == "bass" else 0.0018)
            rms_thresh = min(base_rms, robust_rms * 0.65)
            peak_thresh = min(0.008, robust_rms * 1.35)

            # Optional sibling donor stems (guitar, vocals) for cross-stem acoustic bleed suppression
            y_guitar = None
            y_vocals = None
            if inst in ["other", "piano", "keys"] and audio_path.parent.exists():
                g_path = audio_path.parent / "guitar.wav"
                v_path = audio_path.parent / "vocals.wav"
                if g_path.exists():
                    try:
                        y_guitar, _ = librosa.load(str(g_path), sr=22050, mono=True)
                    except Exception:
                        pass
                if v_path.exists():
                    try:
                        y_vocals, _ = librosa.load(str(v_path), sr=22050, mono=True)
                    except Exception:
                        pass
            
            for instrument in pm.instruments:
                if instrument.is_drum:
                    continue
                
                # 1. Energy gating & cross-stem acoustic bleed rejection
                filtered_notes = []
                for n in instrument.notes:
                    start_idx = int(n.start * sr)
                    end_idx = int(n.end * sr)
                    if start_idx >= len(y):
                        continue
                    chunk = y[start_idx:min(end_idx, len(y))]
                    if len(chunk) == 0:
                        continue
                    rms = float(np.sqrt(np.mean(chunk**2)))
                    peak = float(np.max(np.abs(chunk)))
                    
                    if rms < rms_thresh or peak < peak_thresh:
                        continue

                    # Cross-stem bleed check for 'other'
                    if inst == "other":
                        if y_vocals is not None and start_idx < len(y_vocals):
                            v_chunk = y_vocals[start_idx:min(end_idx, len(y_vocals))]
                            v_rms = float(np.sqrt(np.mean(v_chunk**2))) if len(v_chunk) > 0 else 0.0
                            if v_rms > 0.006 and (rms / (v_rms + 1e-6)) < 0.28:
                                continue
                        if y_guitar is not None and start_idx < len(y_guitar):
                            g_chunk = y_guitar[start_idx:min(end_idx, len(y_guitar))]
                            g_rms = float(np.sqrt(np.mean(g_chunk**2))) if len(g_chunk) > 0 else 0.0
                            if g_rms > 0.004 and (rms / (g_rms + 1e-6)) < 0.45 and n.velocity < 65:
                                continue

                    filtered_notes.append(n)
                        
                # 2. Monophonize vocals, bass, and other (lead strings/fiddle/counter-melody)
                if inst in ["vocals", "bass", "other"]:
                    sorted_notes = sorted(filtered_notes, key=lambda n: (n.start, -n.velocity))
                    mono_notes = []
                    for n in sorted_notes:
                        if not mono_notes:
                            mono_notes.append(n)
                            continue
                        prev = mono_notes[-1]
                        # If start times are within 65ms, it's an overtone harmonic or bleed double-stop
                        if abs(n.start - prev.start) < 0.065:
                            if n.velocity > prev.velocity:
                                mono_notes[-1] = n
                            continue
                        # If overlapping transition
                        if n.start < prev.end:
                            prev.end = max(prev.start + 0.06, n.start)
                        if n.start >= prev.end:
                            mono_notes.append(n)

                    # 3. Vibrato & Micro-note Smoothing:
                    if inst in ["vocals", "other"]:
                        smoothed_notes = []
                        for n in mono_notes:
                            if not smoothed_notes:
                                smoothed_notes.append(n)
                                continue
                            prev = smoothed_notes[-1]
                            gap = n.start - prev.end
                            pitch_diff = abs(n.pitch - prev.pitch)
                            
                            if gap < 0.08 and pitch_diff <= 1 and ((prev.end - prev.start < 0.22) or (n.end - n.start < 0.22)):
                                if (prev.end - prev.start) >= (n.end - n.start):
                                    prev.end = n.end
                                else:
                                    n.start = prev.start
                                    smoothed_notes[-1] = n
                            else:
                                smoothed_notes.append(n)
                        instrument.notes = smoothed_notes
                    else:
                        instrument.notes = mono_notes
                else:
                    instrument.notes = filtered_notes
            
            pm.write(str(midi_path))
            self.logger.info(f"Post-processed MIDI for {instrument_name}: kept {sum(len(i.notes) for i in pm.instruments)} clean notes.")
        except Exception as e:
            self.logger.warning(f"Post-processing MIDI failed for {instrument_name} ({e}), keeping raw MIDI.")

    async def _transcribe_drums(self, audio_path: Path, output_name: str) -> Path:
        """
        Maps percussion transients to standard General MIDI drum notes:
        - Sub/Low onsets (< 250 Hz) -> Kick (36)
        - Mid onsets (250 Hz - 2500 Hz) -> Snare (38)
        - High onsets (> 2500 Hz) -> Closed Hi-Hat (42)
        """
        output_midi_path = self.output_dir / f"{output_name}_drums.mid"
        self.logger.info(f"Transcribing percussion onsets for Drums: {audio_path}")
        
        import pretty_midi
        
        y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
        
        # Onset detection
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, backtrack=True)
        onset_times = librosa.frames_to_time(onset_frames, sr=sr)
        
        pm = pretty_midi.PrettyMIDI()
        drum_inst = pretty_midi.Instrument(program=0, is_drum=True, name="Drums")
        
        for t in onset_times:
            start_samp = int(t * sr)
            end_samp = min(int((t + 0.05) * sr), len(y))
            if start_samp >= end_samp:
                continue
            
            segment = y[start_samp:end_samp]
            n_fft = min(512, len(segment))
            centroid = librosa.feature.spectral_centroid(y=segment, sr=sr, n_fft=n_fft)[0].mean()
            
            if centroid < 300:
                pitch = 36  # Kick
            elif centroid < 2500:
                pitch = 38  # Snare
            else:
                pitch = 42  # Closed Hi-Hat
                
            note = pretty_midi.Note(
                velocity=90,
                pitch=pitch,
                start=float(t),
                end=float(t + 0.08)
            )
            drum_inst.notes.append(note)
            
        pm.instruments.append(drum_inst)
        pm.write(str(output_midi_path))
        return output_midi_path

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
