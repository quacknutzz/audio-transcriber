from pathlib import Path
import math
import logging
import re
import numpy as np
import music21
import pretty_midi

class MusicProcessingService:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        self._song_cache = {}

    def detect_attributes(self, audio_path: Path, drum_path: Path = None, midi_paths: list = None):
        """
        High-precision acoustic & symbolic click-track detector:
        1. Uses high-resolution onset envelope (hop_length=256) to avoid coarse frame quantization.
        2. Refines BPM and downbeat phase offset (t0) using Complex Phasor Periodicity Optimization
           across transcribed note onsets so notes lock dead-center onto Beat 1 of Measure 1.
        3. Detects global harmonic key center via Constant-Q chromagram + Krumhansl-Schmuckler profiles.
        """
        cache_key = str(audio_path.resolve()) if audio_path else "default"
        if cache_key in self._song_cache and not midi_paths:
            return self._song_cache[cache_key]

        try:
            import librosa

            # 1. High-resolution acoustic tempo estimation
            tempo_target = drum_path if (drum_path and drum_path.exists()) else audio_path
            y_tempo, sr_tempo = librosa.load(str(tempo_target), sr=22050, duration=90)
            onset_env = librosa.onset.onset_strength(y=y_tempo, sr=sr_tempo, hop_length=256)
            tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr_tempo, hop_length=256)
            if isinstance(tempo, np.ndarray):
                tempo = float(tempo.item())
            else:
                tempo = float(tempo)

            if len(beats) >= 8:
                beat_times = librosa.frames_to_time(beats, sr=sr_tempo, hop_length=256)
                ibis = np.diff(beat_times)
                median_bpm = 60.0 / float(np.median(ibis))
                tempo = median_bpm

            while tempo < 68.0:
                tempo *= 2.0
            while tempo > 185.0:
                tempo /= 2.0

            # 2. Detect harmonic Key from CQT chromagram using Krumhansl-Schmuckler correlation
            y_harm, sr_harm = librosa.load(str(audio_path), sr=22050, duration=90)
            chroma = librosa.feature.chroma_cqt(y=y_harm, sr=sr_harm)
            chroma_vals = np.sum(chroma, axis=1)

            maj_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
            min_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
            notes = ['C', 'C#', 'D', 'E-', 'E', 'F', 'F#', 'G', 'A-', 'A', 'B-', 'B']

            best_corr = -1e9
            key_note = 'C'
            for i in range(12):
                c_maj = np.corrcoef(chroma_vals, np.roll(maj_profile, i))[0, 1]
                c_min = np.corrcoef(chroma_vals, np.roll(min_profile, i))[0, 1]
                if c_maj > best_corr:
                    best_corr = c_maj
                    key_note = notes[i]
                if c_min > best_corr + 0.05:
                    best_corr = c_min
                    key_note = notes[(i + 3) % 12]  # relative major tonic for clean key signature

            # 3. Complex Phasor Click-Track Refinement if MIDI stems are available
            if not midi_paths and audio_path:
                project_stem = audio_path.stem
                midi_dir = self.output_dir.parent / "midi"
                if midi_dir.exists():
                    midi_paths = list(midi_dir.glob(f"{project_stem}_*.mid"))

            t0 = 0.0
            time_sig_str = "4/4"
            measure_meters = []
            if midi_paths or (audio_path and audio_path.exists()):
                opt_bpm, opt_t0, opt_ts, opt_meters = self._optimize_click_track(
                    midi_paths or [], tempo, audio_path=audio_path, drum_path=drum_path
                )
                tempo = opt_bpm
                t0 = opt_t0
                time_sig_str = opt_ts
                measure_meters = opt_meters

                # Refine Key Signature using symbolic MIDI pitch-class duration fit to minimize accidentals
                from collections import Counter
                pcs_dur = Counter()
                for mp in (midi_paths or []):
                    if "drum" in str(mp).lower():
                        continue
                    try:
                        pm_k = pretty_midi.PrettyMIDI(str(mp))
                        for inst_k in pm_k.instruments:
                            for n_k in inst_k.notes:
                                d_k = n_k.end - n_k.start
                                if d_k >= 0.08:
                                    pcs_dur[n_k.pitch % 12] += d_k
                    except Exception:
                        continue
                tot_dur = sum(pcs_dur.values())
                if tot_dur > 0.5:
                    cand_scales = {
                        'C': ({0,2,4,5,7,9,11}, 0),
                        'G': ({7,9,11,0,2,4,6}, 1),
                        'D': ({2,4,6,7,9,11,1}, 2),
                        'A': ({9,11,1,2,4,6,8}, 3),
                        'E': ({4,6,8,9,11,1,3}, 4),
                        'F': ({5,7,9,10,0,2,4}, -1),
                        'B-': ({10,0,2,3,5,7,9}, -2),
                        'E-': ({3,5,7,8,10,0,2}, -3),
                    }
                    best_k_sc = -1e9
                    for k_cand, (sc_set, sh_cnt) in cand_scales.items():
                        in_scale = sum(d_v for pc_v, d_v in pcs_dur.items() if pc_v in sc_set) / tot_dur
                        k_score = in_scale - 0.008 * abs(sh_cnt) + (0.015 if k_cand == key_note else 0.0)
                        if k_score > best_k_sc:
                            best_k_sc = k_score
                            key_note = k_cand

            self.logger.info(f"Detected Click Track: Tempo={tempo:.1f} BPM, Primary Meter={time_sig_str}, Downbeat t0={t0:.3f}s, Key={key_note}")
            self._song_cache[cache_key] = (tempo, key_note, t0, time_sig_str, measure_meters)
            return tempo, key_note, t0, time_sig_str, measure_meters

        except Exception as e:
            self.logger.warning(f"Attribute detection fallback: {e}")
            return 120.0, "C", 0.0, "4/4", []

    def _optimize_click_track(self, midi_paths: list, init_bpm: float, audio_path: Path = None, drum_path: Path = None):
        """
        Finds the exact studio click-track (BPM, downbeat t0) and dynamic per-measure time signature
        sequence (supporting 2/4, 3/4, 4/4, 5/4, 6/4, 6/8, 7/4, 12/8 and section meter changes!)
        by fusing CP-JKU's beat_this neural beat/downbeat transformer with ensemble MIDI note onsets
        and Per-Beat Weighted Viterbi Dynamic Programming.
        """
        onsets = []
        weights = []
        bar_weights = []
        midi_notes_info = []

        for mp in midi_paths:
            try:
                pm = pretty_midi.PrettyMIDI(str(mp))
                if not pm.instruments:
                    continue
                name_l = str(mp).lower()
                if "drum" in name_l:
                    continue
                is_rhythm = ("bass" in name_l or "guitar" in name_l)
                for n in pm.instruments[0].notes:
                    dur = n.end - n.start
                    if dur < 0.08 or n.velocity < 35:
                        continue
                    onsets.append(n.start)
                    w = dur * (n.velocity / 100.0) * (2.0 if is_rhythm else 1.0)
                    weights.append(w)
                    is_anchor = is_rhythm and dur >= 0.65
                    bar_weights.append(w * (4.0 if is_anchor else 0.5))
                    midi_notes_info.append((n.start, dur, n.velocity, is_anchor))
            except Exception:
                continue

        # 1. Obtain neural beat & downbeat probability curves from CP-JKU beat_this (ISMIR 2024)
        # Always run beat_this on the full mix (audio_path) so drumless intros/breakdowns/bridges are tracked accurately!
        beat_prob = None
        db_prob = None
        y_audio = None
        sr_audio = 22050
        fps = 50.0
        target_wav = audio_path if (audio_path and audio_path.exists()) else drum_path
        if target_wav and target_wav.exists():
            try:
                import librosa
                import torch
                from beat_this.inference import Audio2Frames
                y_audio, sr_audio = librosa.load(str(target_wav), sr=22050, mono=True)
                device = 'cuda' if torch.cuda.is_available() else 'cpu'
                a2f = Audio2Frames(checkpoint_path='final0', device=device)
                beat_logits, db_logits = a2f(y_audio, sr_audio)
                beat_prob = torch.sigmoid(beat_logits).detach().cpu().numpy()
                db_prob = torch.sigmoid(db_logits).detach().cpu().numpy()
                del a2f, beat_logits, db_logits
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

                ac = np.correlate(beat_prob - np.mean(beat_prob), beat_prob - np.mean(beat_prob), mode='full')
                ac = ac[len(ac) // 2:]
                if len(ac) > 48:
                    best_lag = 14 + int(np.argmax(ac[14:48]))
                    # Prevent 2-beat subharmonic lock (e.g. picking 78 BPM instead of 156 BPM)
                    if best_lag >= 28:
                        half_lag = best_lag // 2
                        sub_peak = float(np.max(ac[max(14, half_lag - 1):half_lag + 2]))
                        if sub_peak >= 0.55 * float(ac[best_lag]):
                            best_lag = int(max(14, half_lag - 1) + np.argmax(ac[max(14, half_lag - 1):half_lag + 2]))
                    neural_bpm = 60.0 * fps / float(best_lag)
                    while neural_bpm < 68.0:
                        neural_bpm *= 2.0
                    while neural_bpm > 185.0:
                        neural_bpm /= 2.0
                    init_bpm = neural_bpm
            except Exception as bt_err:
                self.logger.warning(f"beat_this neural tracker fallback: {bt_err}")

        if len(onsets) < 8 and beat_prob is None:
            return round(init_bpm), 0.0, "4/4", []

        onsets_arr = np.array(onsets) if len(onsets) > 0 else np.array([0.0])
        weights_arr = np.array(weights) if len(weights) > 0 else np.array([1.0])
        weights_arr /= (np.sum(weights_arr) + 1e-9)
        earliest = float(np.min(onsets_arr)) if len(onsets) > 0 else 0.0

        best_score = -1e9
        best_bpm = round(init_bpm)
        best_t0 = earliest

        low_bpm = max(65, int(round(init_bpm)) - 5)
        high_bpm = min(190, int(round(init_bpm)) + 6)
        frame_times = (np.arange(len(beat_prob)) / fps) if beat_prob is not None else None

        for bpm_cand in np.linspace(low_bpm, high_bpm, (high_bpm - low_bpm) * 10 + 1):
            beat_sec = 60.0 / float(bpm_cand)
            score = 0.0
            angle = 0.0
            if len(onsets) >= 8:
                phases_beat = 2.0 * np.pi * (onsets_arr - earliest) / beat_sec
                phases_eighth = 4.0 * np.pi * (onsets_arr - earliest) / beat_sec
                z_beat = np.sum(weights_arr * np.exp(1j * phases_beat))
                z_eighth = np.sum(weights_arr * np.exp(1j * phases_eighth))
                score += (np.abs(z_beat) * 1.0 + np.abs(z_eighth) * 0.5)
                angle = float(np.angle(z_beat))
            if beat_prob is not None:
                z_neural = np.mean(beat_prob * np.exp(1j * 2.0 * np.pi * (frame_times - earliest) / beat_sec))
                score += np.abs(z_neural) * 1.6
                angle = float(np.angle(z_neural))

            prior = 1.0 - 0.012 * abs(bpm_cand - init_bpm)
            score *= prior

            if score > best_score:
                best_score = score
                best_bpm = float(bpm_cand)
                beat_phase = earliest + (angle / (2.0 * np.pi)) * beat_sec
                while beat_phase > earliest + 0.2 * beat_sec:
                    beat_phase -= beat_sec
                while beat_phase < 0.0:
                    beat_phase += beat_sec
                best_t0 = beat_phase

        # 2. Construct Beat Lattice and Run Viterbi Dynamic Meter & Barline Tracking over M in {2, 3, 4, 5, 6, 7}
        beat_sec = 60.0 / best_bpm
        max_note_time = float(np.max(onsets_arr)) + beat_sec if len(onsets) > 0 else 0.0
        audio_dur = (len(beat_prob) / fps) if beat_prob is not None else 0.0
        max_time = max(max_note_time, min(audio_dur, max_note_time + 2.0 * beat_sec) if max_note_time > 0 else audio_dur)

        start_phase = best_t0
        while start_phase - beat_sec >= 0.0:
            start_phase -= beat_sec
        beat_times = np.arange(start_phase, max_time + 0.1 * beat_sec, beat_sec)
        N = len(beat_times)

        if N >= 6:
            S_db = np.zeros(N, dtype=np.float64)
            S_audio = np.zeros(N, dtype=np.float64)
            S_midi = np.zeros(N, dtype=np.float64)

            # Low-pass filter y_audio (~250 Hz moving average) so kick/bass downbeats stand out above hi-hats/snares
            y_low = None
            if y_audio is not None and len(y_audio) > 100:
                win_lp = max(3, int(sr_audio / 250))
                kernel = np.ones(win_lp, dtype=np.float32) / float(win_lp)
                y_low = np.convolve(y_audio, kernel, mode='same')

            for k, bt in enumerate(beat_times):
                # Snap bt locally within +-0.22*beat_sec to the exact neural beat peak to eliminate micro-drift
                bt_actual = bt
                if beat_prob is not None:
                    f_center = int(round(bt * fps))
                    half_r = max(2, int(round(0.22 * beat_sec * fps)))
                    r_s = max(0, f_center - half_r)
                    r_e = min(len(beat_prob), f_center + half_r + 1)
                    if r_e > r_s:
                        peak_f = r_s + int(np.argmax(beat_prob[r_s:r_e]))
                        if beat_prob[peak_f] > 0.15:
                            bt_actual = peak_f / fps
                        w_s = max(0, peak_f - 2)
                        w_e = min(len(db_prob), peak_f + 3)
                        if w_e > w_s:
                            S_db[k] = float(np.max(db_prob[w_s:w_e]))
                if y_audio is not None:
                    s_idx = max(0, int((bt_actual - 0.02) * sr_audio))
                    e_idx = min(len(y_audio), int((bt_actual + 0.12) * sr_audio))
                    if e_idx > s_idx:
                        seg_full = y_audio[s_idx:e_idx]
                        seg_low = y_low[s_idx:e_idx] if y_low is not None else seg_full
                        S_audio[k] = float(np.sqrt(np.mean(seg_low**2)) * 2.0 + np.sqrt(np.mean(seg_full**2)))

            for n_start, n_dur, n_vel, is_anchor in midi_notes_info:
                k_idx = int(np.argmin(np.abs(beat_times - n_start)))
                if abs(beat_times[k_idx] - n_start) < 0.28 * beat_sec:
                    S_midi[k_idx] += (n_dur / beat_sec) * (n_vel / 100.0) * (2.0 if is_anchor else 0.8)

            def _local_zscore(arr, half_win=12):
                std_global = float(np.std(arr))
                if std_global < 1e-6:
                    return np.zeros_like(arr)
                out = np.zeros_like(arr)
                for idx_a in range(len(arr)):
                    w0 = max(0, idx_a - half_win)
                    w1 = min(len(arr), idx_a + half_win + 1)
                    local_slice = arr[w0:w1]
                    l_std = float(np.std(local_slice))
                    if l_std < 1e-5:
                        out[idx_a] = (arr[idx_a] - float(np.mean(arr))) / std_global
                    else:
                        out[idx_a] = (arr[idx_a] - float(np.mean(local_slice))) / l_std
                return out

            S_combined = 1.4 * _local_zscore(S_db) + 1.0 * _local_zscore(S_audio) + 0.65 * _local_zscore(S_midi)
            S_norm = _local_zscore(S_combined)

            meters = [2, 3, 4, 5, 6, 7]
            priors = {2: -0.04, 3: 0.02, 4: 0.06, 5: -0.07, 6: -0.03, 7: -0.08}
            switch_cost = 4.2
            min_bars = 4  # Require at least 4 consecutive bars of a meter per section (prevents 1-bar glitches)

            dp = {}
            backptr = {}
            for m in meters:
                for k0 in range(min(m, N - 2)):
                    skip_cost = float(np.sum(np.maximum(0.0, S_norm[:k0]))) if k0 > 0 else 0.0
                    dp[(k0, m, 1)] = -skip_cost
                    backptr[(k0, m, 1)] = None

            terminal_candidates = {}
            for k in range(N):
                for m in meters:
                    for run in range(1, min_bars + 1):
                        if (k, m, run) not in dp:
                            continue
                        k_next = k + m
                        if k_next > N:
                            continue
                        internal = np.mean(S_norm[k + 1:k_next]) if k_next > k + 1 else 0.0
                        emit = m * ((S_norm[k] - internal) + priors[m])
                        cand_base = dp[(k, m, run)] + emit

                        # Check if k_next is near the end of the beat lattice (no further full bar required)
                        # A terminal section must have completed at least min_bars (4 bars), unless the entire song is shorter than 4 bars.
                        if k_next >= N - m and (run >= min_bars or k_next < m * (run + 1)):
                            if cand_base > terminal_candidates.get((k_next, m, run), -1e9):
                                terminal_candidates[(k_next, m, run)] = cand_base
                                backptr[(k_next, m, run, "TERM")] = (k, m, run)

                        if k_next < N:
                            # 1. Stay in the same meter m (always allowed)
                            next_run = min(min_bars, run + 1)
                            if cand_base > dp.get((k_next, m, next_run), -1e9):
                                dp[(k_next, m, next_run)] = cand_base
                                backptr[(k_next, m, next_run)] = (k, m, run)

                            # 2. Switch to a new meter m_next != m (only allowed after completing min_bars in meter m)
                            if run >= min_bars:
                                for m_next in meters:
                                    if m_next == m:
                                        continue
                                    cand_switch = cand_base - switch_cost
                                    if cand_switch > dp.get((k_next, m_next, 1), -1e9):
                                        dp[(k_next, m_next, 1)] = cand_switch
                                        backptr[(k_next, m_next, 1)] = (k, m, run)

            if terminal_candidates:
                best_term = max(terminal_candidates.keys(), key=lambda st: terminal_candidates[st])
                bars = []
                curr = backptr.get((best_term[0], best_term[1], best_term[2], "TERM"))
                while curr is not None:
                    bars.append((curr[0], curr[1]))
                    curr = backptr.get(curr)
                bars.reverse()

                if bars:
                    first_k = bars[0][0]
                    best_bar_t0 = float(start_phase + first_k * beat_sec)
                    init_m = bars[0][1]
                    substantive_early = [
                        n_s for (n_s, n_d, n_v, _) in midi_notes_info
                        if n_d >= 0.18 and n_v >= 48
                    ]
                    min_substantive = min(substantive_early) if substantive_early else best_bar_t0
                    while best_bar_t0 > min_substantive + 0.35 * beat_sec:
                        best_bar_t0 -= init_m * beat_sec
                        bars.insert(0, (first_k - init_m, init_m))
                        first_k -= init_m

                    # Snap best_bar_t0 to the exact physical attack transient of Measure 1 Beat 1 (eliminates neural phase lag)
                    c0_onsets = [
                        n_s for (n_s, n_d, n_v, _) in midi_notes_info
                        if n_d >= 0.12 and n_v >= 45 and abs(n_s - best_bar_t0) <= 0.22 * beat_sec
                    ]
                    if c0_onsets:
                        best_bar_t0 = float(min(c0_onsets))

                    from collections import Counter
                    m_counts = Counter(m_len for _, m_len in bars)
                    dominant_m = m_counts.most_common(1)[0][0]

                    # If the song is predominantly 6-pulse bars at >=105 pulse BPM, interpret as compound 6/8
                    # where each pulse is an eighth note (0.5 quarterLength) and each bar is 3.0 quarterLengths.
                    is_compound_6_8 = (
                        dominant_m == 6
                        and m_counts[6] >= 0.75 * len(bars)
                        and best_bpm >= 105.0
                    )
                    if is_compound_6_8:
                        best_bpm = best_bpm / 2.0
                        beat_sec = 60.0 / best_bpm

                    measure_meters = []
                    for b_k, m_len in bars:
                        if is_compound_6_8 and m_len == 6:
                            measure_meters.append((3.0, "6/8"))
                        elif m_len == 3:
                            # Check compound 6/8 vs simple 3/4 feel
                            ts_label = "3/4"
                            if len(onsets) >= 8:
                                t_s = float(start_phase + b_k * beat_sec)
                                t_e = t_s + 3.0 * beat_sec
                                sub_onsets = onsets_arr[(onsets_arr >= t_s) & (onsets_arr < t_e)]
                                if len(sub_onsets) >= 3:
                                    c_score = float(np.mean(np.cos(2.0 * np.pi * (sub_onsets - t_s) / (1.5 * beat_sec))))
                                    s_score = float(np.mean(np.cos(2.0 * np.pi * (sub_onsets - t_s) / beat_sec)))
                                    if c_score > s_score + 0.15:
                                        ts_label = "6/8"
                            measure_meters.append((3.0, ts_label))
                        elif m_len == 6:
                            measure_meters.append((6.0, "6/4"))
                        else:
                            q_len = float(m_len) * (0.5 if is_compound_6_8 else 1.0)
                            measure_meters.append((q_len, f"{int(round(q_len))}/4"))

                    primary_ts = Counter(ts for _, ts in measure_meters).most_common(1)[0][0]
                    return best_bpm, best_bar_t0, primary_ts, measure_meters

        return best_bpm, best_t0, "4/4", []

    @staticmethod
    def _fold_pitch_to_window(pitch: int, low: int, high: int) -> int:
        """Folds a MIDI pitch by octaves so it lands cleanly inside [low, high]."""
        p = int(pitch)
        while p < low:
            p += 12
        while p > high:
            p -= 12
        return p

    @staticmethod
    def _midi_to_spelled_pitch(midi_val: int, key_sharps: int = 0) -> music21.pitch.Pitch:
        """
        Spells a MIDI integer enharmonically to match the active key signature direction
        (sharps for key_sharps >= 0, flats for key_sharps < 0), preventing music21.chord.Chord
        from spelling F# as Gb, D# as Eb, or G# as Ab inside sharp keys.
        """
        sharp_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        flat_names = ['C', 'D-', 'D', 'E-', 'E', 'F', 'G-', 'G', 'A-', 'A', 'B-', 'B']
        pc = int(midi_val) % 12
        octave = (int(midi_val) // 12) - 1
        name = sharp_names[pc] if key_sharps >= 0 else flat_names[pc]
        return music21.pitch.Pitch(f"{name}{octave}")

    @staticmethod
    def _get_diatonic_pcs(key_obj) -> set:
        """Returns the set of 7 diatonic pitch classes (0-11) for a music21 Key or KeySignature."""
        try:
            if hasattr(key_obj, 'getPitches'):
                return {p.pitchClass for p in key_obj.getPitches()}
            sharps = getattr(key_obj, 'sharps', 0) or 0
            tonic_pc = (sharps * 7) % 12
            maj_intervals = [0, 2, 4, 5, 7, 9, 11]
            return {(tonic_pc + iv) % 12 for iv in maj_intervals}
        except Exception:
            return {0, 2, 4, 5, 7, 9, 11}

    def _voice_polyphonic_chord(self, raw_pitches: list, target_low: int = 57, target_high: int = 76, max_voices: int = 3) -> list:
        """
        Converts raw polyphonic MIDI pitches into a clean, close-position staff voicing:
        - Deduplicates pitch classes (eliminates octave overtone stacks).
        - Places all chord tones within the comfortable staff tessitura [target_low, target_high].
        - Limits chord span to <= 12 semitones (1 octave) so stems never stretch into skyscrapers.
        - Caps polyphony to at most max_voices (clean triad/dyad).
        """
        if not raw_pitches:
            return []

        # Preserve lowest pitch class as chord root/bass anchor
        sorted_raw = sorted(raw_pitches)
        root_pc = sorted_raw[0] % 12

        seen_pcs = set()
        unique_pcs = []
        for p in sorted_raw:
            pc = p % 12
            if pc not in seen_pcs:
                seen_pcs.add(pc)
                unique_pcs.append(pc)

        if len(unique_pcs) > max_voices:
            # Keep lowest pitch class (root), highest pitch class (melody), and inner third/fifth
            unique_pcs = [unique_pcs[0], unique_pcs[1], unique_pcs[-1]][:max_voices]

        # Place root in the lower-middle part of the staff window
        root_pitch = target_low + ((root_pc - (target_low % 12)) % 12)
        if root_pitch > target_high - 7 and root_pitch - 12 >= target_low - 2:
            root_pitch -= 12

        voiced = [root_pitch]
        for pc in unique_pcs[1:]:
            # Place remaining chord tones above root_pitch within 1 octave (close position)
            cand = root_pitch + ((pc - root_pc) % 12)
            if cand > target_high:
                cand -= 12
            if cand < target_low:
                cand += 12
            voiced.append(cand)

        voiced = sorted(list(set(voiced)))
        # Ensure total spread of chord is at most 12 semitones
        if len(voiced) > 1 and (voiced[-1] - voiced[0]) > 12:
            voiced[-1] -= 12
            voiced = sorted(list(set(voiced)))

        return voiced

    @staticmethod
    def _decompose_rest_interval(start_q: float, end_q: float, time_sig_str: str = "4/4") -> list:
        """
        Decomposes a silent interval [start_q, end_q] within a measure
        strictly along the active meter's hierarchy (4/4, 3/4, or 6/8):
        - 4/4: splits across half-bar (2.0), then beat boundaries (1.0, 3.0). Rests in {4.0, 2.0, 1.0, 0.5}.
        - 3/4: full measure [0.0, 3.0] -> 3.0; otherwise splits at beat boundaries (1.0, 2.0) into {1.0, 0.5} (never 2.0 half-rests in 3/4).
        - 6/8: full measure [0.0, 3.0] -> 3.0; compound half-bar [0.0, 1.5] or [1.5, 3.0] -> 1.5 (dotted-quarter rest); otherwise splits at 1.5 and beat subdivisions.
        """
        a = round(start_q * 2.0) / 2.0
        b = round(end_q * 2.0) / 2.0
        if b <= a:
            return []

        if time_sig_str == "2/4":
            if a == 0.0 and b == 2.0:
                return [(0.0, 2.0)]
            if a < 1.0 and b > 1.0:
                return (
                    MusicProcessingService._decompose_rest_interval(a, 1.0, "2/4") +
                    MusicProcessingService._decompose_rest_interval(1.0, b, "2/4")
                )
            return [(a, round(b - a, 2))]

        if time_sig_str == "5/4":
            # Standard 3+2 metric grouping: [0.0, 3.0] as 3/4 and [3.0, 5.0] as 2/4
            if a < 3.0 and b > 3.0:
                return (
                    MusicProcessingService._decompose_rest_interval(a, 3.0, "3/4") +
                    [(round(off + 3.0, 2), d) for off, d in MusicProcessingService._decompose_rest_interval(0.0, round(b - 3.0, 2), "2/4")]
                )
            if b <= 3.0:
                return MusicProcessingService._decompose_rest_interval(a, b, "3/4")
            return [(round(off + 3.0, 2), d) for off, d in MusicProcessingService._decompose_rest_interval(round(a - 3.0, 2), round(b - 3.0, 2), "2/4")]

        if time_sig_str == "6/4":
            # Standard 3+3 metric grouping: [0.0, 3.0] as 3/4 and [3.0, 6.0] as 3/4
            if a < 3.0 and b > 3.0:
                return (
                    MusicProcessingService._decompose_rest_interval(a, 3.0, "3/4") +
                    [(round(off + 3.0, 2), d) for off, d in MusicProcessingService._decompose_rest_interval(0.0, round(b - 3.0, 2), "3/4")]
                )
            if b <= 3.0:
                return MusicProcessingService._decompose_rest_interval(a, b, "3/4")
            return [(round(off + 3.0, 2), d) for off, d in MusicProcessingService._decompose_rest_interval(round(a - 3.0, 2), round(b - 3.0, 2), "3/4")]

        if time_sig_str == "7/4":
            # Standard 4+3 metric grouping: [0.0, 4.0] as 4/4 and [4.0, 7.0] as 3/4
            if a < 4.0 and b > 4.0:
                return (
                    MusicProcessingService._decompose_rest_interval(a, 4.0, "4/4") +
                    [(round(off + 4.0, 2), d) for off, d in MusicProcessingService._decompose_rest_interval(0.0, round(b - 4.0, 2), "3/4")]
                )
            if b <= 4.0:
                return MusicProcessingService._decompose_rest_interval(a, b, "4/4")
            return [(round(off + 4.0, 2), d) for off, d in MusicProcessingService._decompose_rest_interval(round(a - 4.0, 2), round(b - 4.0, 2), "3/4")]

        if time_sig_str == "6/8":
            if a == 0.0 and b == 3.0:
                return [(0.0, 3.0)]
            if a < 1.5 and b > 1.5:
                return (
                    MusicProcessingService._decompose_rest_interval(a, 1.5, "6/8") +
                    MusicProcessingService._decompose_rest_interval(1.5, b, "6/8")
                )
            if (a == 0.0 and b == 1.5) or (a == 1.5 and b == 3.0):
                return [(a, 1.5)]
            # Inside a 1.5-beat compound half ([0.0, 1.5] or [1.5, 3.0]), split into 0.5 eighth rests if 1.0
            if round(b - a, 2) == 1.0:
                return [(a, 0.5), (round(a + 0.5, 2), 0.5)]
            return [(a, round(b - a, 2))]

        if time_sig_str == "3/4":
            if a == 0.0 and b == 3.0:
                return [(0.0, 3.0)]
            for boundary in (1.0, 2.0):
                if a < boundary and b > boundary:
                    return (
                        MusicProcessingService._decompose_rest_interval(a, boundary, "3/4") +
                        MusicProcessingService._decompose_rest_interval(boundary, b, "3/4")
                    )
            return [(a, round(b - a, 2))]

        # Default 4/4 metric hierarchy
        if a == 0.0 and b == 4.0:
            return [(0.0, 4.0)]
        # Split across the half-bar (2.0)
        if a < 2.0 and b > 2.0:
            return (
                MusicProcessingService._decompose_rest_interval(a, 2.0, "4/4") +
                MusicProcessingService._decompose_rest_interval(2.0, b, "4/4")
            )
        # Inside Half 1 [0.0, 2.0] or Half 2 [2.0, 4.0]
        if (a == 0.0 and b == 2.0) or (a == 2.0 and b == 4.0):
            return [(a, 2.0)]
        mid_beat = 1.0 if b <= 2.0 else 3.0
        if a < mid_beat and b > mid_beat:
            return (
                MusicProcessingService._decompose_rest_interval(a, mid_beat, "4/4") +
                MusicProcessingService._decompose_rest_interval(mid_beat, b, "4/4")
            )
        return [(a, round(b - a, 2))]

    @staticmethod
    def _decompose_note_interval(start_q: float, end_q: float, tie_in: bool = False, tie_out: bool = False, time_sig_str: str = "4/4") -> list:
        """
        Decomposes a note/chord interval [start_q, end_q] inside a measure into
        canonical engraving durations for any active meter (2/4, 3/4, 4/4, 5/4, 6/4, 6/8, 7/4):
        - Eliminates double-dotted notes (3.5, 1.75) and awkward cross-beat syncopations.
        - Returns list of (offset, dur, tie_type) tuples.
        """
        a = round(start_q * 2.0) / 2.0
        b = round(end_q * 2.0) / 2.0
        dur = round(b - a, 2)
        if dur <= 0:
            return []

        if time_sig_str == "2/4":
            canonical_24 = {
                (0.0, 2.0), (0.0, 1.5), (0.5, 2.0),
                (0.0, 1.0), (0.5, 1.5), (1.0, 2.0),
                (0.0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0),
            }
            if (a, b) in canonical_24:
                return MusicProcessingService._attach_ties([(a, dur)], tie_in, tie_out)
            if a < 1.0 and b > 1.0:
                raw_segs = [(a, round(1.0 - a, 2)), (1.0, round(b - 1.0, 2))]
                return MusicProcessingService._attach_ties(raw_segs, tie_in, tie_out)
            return MusicProcessingService._attach_ties([(a, dur)], tie_in, tie_out)

        if time_sig_str == "5/4":
            # 3+2 split at 3.0
            if a < 3.0 and b > 3.0:
                left = MusicProcessingService._decompose_note_interval(a, 3.0, False, False, "3/4")
                right = MusicProcessingService._decompose_note_interval(0.0, round(b - 3.0, 2), False, False, "2/4")
                raw_segs = [(x[0], x[1]) for x in left] + [(round(x[0] + 3.0, 2), x[1]) for x in right]
                return MusicProcessingService._attach_ties(raw_segs, tie_in, tie_out)
            if b <= 3.0:
                return MusicProcessingService._decompose_note_interval(a, b, tie_in, tie_out, "3/4")
            right = MusicProcessingService._decompose_note_interval(round(a - 3.0, 2), round(b - 3.0, 2), False, False, "2/4")
            raw_segs = [(round(x[0] + 3.0, 2), x[1]) for x in right]
            return MusicProcessingService._attach_ties(raw_segs, tie_in, tie_out)

        if time_sig_str == "6/4":
            # 3+3 split at 3.0
            if a < 3.0 and b > 3.0:
                left = MusicProcessingService._decompose_note_interval(a, 3.0, False, False, "3/4")
                right = MusicProcessingService._decompose_note_interval(0.0, round(b - 3.0, 2), False, False, "3/4")
                raw_segs = [(x[0], x[1]) for x in left] + [(round(x[0] + 3.0, 2), x[1]) for x in right]
                return MusicProcessingService._attach_ties(raw_segs, tie_in, tie_out)
            if b <= 3.0:
                return MusicProcessingService._decompose_note_interval(a, b, tie_in, tie_out, "3/4")
            right = MusicProcessingService._decompose_note_interval(round(a - 3.0, 2), round(b - 3.0, 2), False, False, "3/4")
            raw_segs = [(round(x[0] + 3.0, 2), x[1]) for x in right]
            return MusicProcessingService._attach_ties(raw_segs, tie_in, tie_out)

        if time_sig_str == "7/4":
            # 4+3 split at 4.0
            if a < 4.0 and b > 4.0:
                left = MusicProcessingService._decompose_note_interval(a, 4.0, False, False, "4/4")
                right = MusicProcessingService._decompose_note_interval(0.0, round(b - 4.0, 2), False, False, "3/4")
                raw_segs = [(x[0], x[1]) for x in left] + [(round(x[0] + 4.0, 2), x[1]) for x in right]
                return MusicProcessingService._attach_ties(raw_segs, tie_in, tie_out)
            if b <= 4.0:
                return MusicProcessingService._decompose_note_interval(a, b, tie_in, tie_out, "4/4")
            right = MusicProcessingService._decompose_note_interval(round(a - 4.0, 2), round(b - 4.0, 2), False, False, "3/4")
            raw_segs = [(round(x[0] + 4.0, 2), x[1]) for x in right]
            return MusicProcessingService._attach_ties(raw_segs, tie_in, tie_out)

        if time_sig_str == "6/8":
            # Compound duple (two 1.5-quarter beats: [0.0, 1.5] and [1.5, 3.0])
            if a == 0.0 and b == 3.0:
                return MusicProcessingService._attach_ties([(0.0, 3.0)], tie_in, tie_out)
            if a < 1.5 and b > 1.5:
                left = MusicProcessingService._decompose_note_interval(a, 1.5, False, False, "6/8")
                right = MusicProcessingService._decompose_note_interval(1.5, b, False, False, "6/8")
                raw_segs = [(x[0], x[1]) for x in (left + right)]
                return MusicProcessingService._attach_ties(raw_segs, tie_in, tie_out)
            return MusicProcessingService._attach_ties([(a, dur)], tie_in, tie_out)

        if time_sig_str == "3/4":
            # Simple triple (3.0 quarter-beats: [0.0, 1.0, 2.0, 3.0])
            if a == 0.0 and dur == 2.5:
                segs = [(0.0, 2.0), (2.0, 0.5)] if tie_out else [(0.0, 2.0)]
                return MusicProcessingService._attach_ties(segs, tie_in, tie_out)
            if a == 0.5 and dur == 2.5:
                segs = [(0.5, 0.5), (1.0, 2.0)]
                return MusicProcessingService._attach_ties(segs, tie_in, tie_out)
            canonical_34 = {
                (0.0, 3.0), (0.0, 2.0), (1.0, 3.0),
                (0.0, 1.5), (0.5, 2.0), (1.0, 2.5), (1.5, 3.0),
                (0.0, 1.0), (0.5, 1.5), (1.0, 2.0), (1.5, 2.5), (2.0, 3.0),
                (0.0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 3.0),
            }
            if (a, b) in canonical_34:
                return MusicProcessingService._attach_ties([(a, dur)], tie_in, tie_out)
            for boundary in (1.0, 2.0):
                if a < boundary and b > boundary:
                    raw_segs = [(a, round(boundary - a, 2)), (boundary, round(b - boundary, 2))]
                    return MusicProcessingService._attach_ties(raw_segs, tie_in, tie_out)
            return MusicProcessingService._attach_ties([(a, dur)], tie_in, tie_out)

        # Default 4/4 decomposition
        # Snap 3.5-beat duration starting at 0.0 to clean 3.0 dotted-half (or 4.0 whole if tied out)
        if a == 0.0 and dur == 3.5:
            if tie_out:
                dur = 4.0
                b = 4.0
            else:
                dur = 3.0
                b = 3.0
        elif a == 0.5 and dur == 3.5:
            # 0.5 to 4.0 -> split at 1.0 into 0.5 + 3.0 tied
            segments = [(0.5, 0.5), (1.0, 3.0)]
            return MusicProcessingService._attach_ties(segments, tie_in, tie_out)
        elif dur == 2.5:
            if a == 0.0:
                # 0.0 to 2.5 -> clean 2.0 half note (or 2.0 + 0.5 if tied)
                if not tie_out:
                    segments = [(0.0, 2.0)]
                else:
                    segments = [(0.0, 2.0), (2.0, 0.5)]
                return MusicProcessingService._attach_ties(segments, tie_in, tie_out)
            elif a == 1.5:
                segments = [(1.5, 0.5), (2.0, 2.0)]
                return MusicProcessingService._attach_ties(segments, tie_in, tie_out)

        # Canonical single-note durations that don't illegally obscure the half-bar (2.0)
        canonical_pairs = {
            (0.0, 4.0), (0.0, 3.0), (1.0, 4.0),
            (0.0, 2.0), (1.0, 3.0), (2.0, 4.0),
            (0.0, 1.5), (0.5, 2.0), (2.0, 3.5), (2.5, 4.0),
            (0.0, 1.0), (0.5, 1.5), (1.0, 2.0), (1.5, 2.5), (2.0, 3.0), (2.5, 3.5), (3.0, 4.0),
            (0.0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 3.5), (3.5, 4.0),
        }

        if (a, b) in canonical_pairs:
            return MusicProcessingService._attach_ties([(a, round(b - a, 2))], tie_in, tie_out)

        # Otherwise split cleanly at the half-bar (2.0)
        if a < 2.0 and b > 2.0:
            left = MusicProcessingService._decompose_note_interval(a, 2.0, tie_in=False, tie_out=False, time_sig_str="4/4")
            right = MusicProcessingService._decompose_note_interval(2.0, b, tie_in=False, tie_out=False, time_sig_str="4/4")
            raw_segs = [(x[0], x[1]) for x in (left + right)]
            return MusicProcessingService._attach_ties(raw_segs, tie_in, tie_out)

        # Fallback split at beat boundary (1.0 or 3.0)
        mid = 1.0 if b <= 2.0 else 3.0
        if a < mid and b > mid:
            raw_segs = [(a, round(mid - a, 2)), (mid, round(b - mid, 2))]
            return MusicProcessingService._attach_ties(raw_segs, tie_in, tie_out)

        return MusicProcessingService._attach_ties([(a, dur)], tie_in, tie_out)

    @staticmethod
    def _attach_ties(segments: list, tie_in: bool, tie_out: bool) -> list:
        n = len(segments)
        result = []
        for i, (off, dur) in enumerate(segments):
            has_prev = (i > 0) or tie_in
            has_next = (i < n - 1) or tie_out
            if has_prev and has_next:
                t_val = "continue"
            elif has_prev:
                t_val = "stop"
            elif has_next:
                t_val = "start"
            else:
                t_val = None
            result.append((off, dur, t_val))
        return result

    def midi_to_xml(self, midi_path: Path, output_name: str, audio_ref_path: Path = None, drum_ref_path: Path = None, master_key_sig=None) -> Path:
        """
        Converts a MIDI file to engraver-grade, beat-locked MusicXML:
        - Locks all note timings to the song's true click-track (BPM, downbeat t0) and dynamic section time signatures.
        - Enforces staff-centered tessitura and close-position chord voicing (zero skyscraper ledger lines).
        - Decomposes all notes and rests along each measure's active metric hierarchy (2/4, 3/4, 4/4, 5/4, 6/4, 6/8, 7/4).
        - Applies automatic eighth-note beaming (makeBeams) per beat.
        """
        output_xml_path = self.output_dir / f"{output_name}.musicxml"
        self.logger.info(f"Converting MIDI to XML: {midi_path} -> {output_xml_path}")

        try:
            # 1. Detect Beat-Locked Click Track (BPM, Key, Downbeat t0, Primary Meter & Per-Measure Meters)
            tempo_bpm = 120.0
            key_tonic = "C"
            t0 = 0.0
            time_sig_str = "4/4"
            measure_meters = []
            if audio_ref_path and audio_ref_path.exists():
                res = self.detect_attributes(audio_ref_path, drum_ref_path)
                if len(res) == 5:
                    tempo_bpm, key_tonic, t0, time_sig_str, measure_meters = res
                elif len(res) == 4:
                    tempo_bpm, key_tonic, t0, time_sig_str = res
                elif len(res) == 3:
                    tempo_bpm, key_tonic, t0 = res
                else:
                    tempo_bpm, key_tonic = res

            name_lower = output_name.lower()
            is_vocal = any(m in name_lower for m in ["vocal", "voice"])
            is_bass = "bass" in name_lower
            is_guitar = "guitar" in name_lower
            is_other = "other" in name_lower
            is_piano = any(p_k in name_lower for p_k in ["piano", "keys"])
            is_drum = any(d in name_lower for d in ["drums", "drum", "percussion"])
            is_mono = is_vocal or is_bass or is_other

            # 2. Parse MIDI
            pm = pretty_midi.PrettyMIDI(str(midi_path))
            if not pm.instruments:
                raise ValueError("MIDI file contains no instrument tracks")

            inst = pm.instruments[0]

            clean_notes = [
                n for n in inst.notes
                if not (n.end - n.start < 0.08 and n.velocity < 40)
            ]

            # Cross-Stem Symbolic Bleed Cancellation for 'other' and 'piano':
            # Reject notes that are direct harmonic/octave bleed from louder simultaneous Guitar or Vocal notes.
            if (is_other or is_piano) and midi_path.parent.exists():
                song_prefix = re.sub(r'_(other|piano|keys).*$', '', midi_path.stem, flags=re.IGNORECASE)
                donor_notes = []
                for donor_tag in ["guitar", "vocals"]:
                    for dm_path in midi_path.parent.glob(f"{song_prefix}_{donor_tag}*.mid"):
                        try:
                            pm_d = pretty_midi.PrettyMIDI(str(dm_path))
                            for inst_d in pm_d.instruments:
                                for nd in inst_d.notes:
                                    if nd.end - nd.start >= 0.08:
                                        donor_notes.append((nd.start, nd.end, nd.pitch, nd.velocity, donor_tag))
                        except Exception:
                            continue
                if donor_notes:
                    debleeded = []
                    for n in clean_notes:
                        is_bleed = False
                        n_dur = max(0.05, n.end - n.start)
                        for d_s, d_e, d_p, d_v, d_tag in donor_notes:
                            ov = min(n.end, d_e) - max(n.start, d_s)
                            near_onset = abs(n.start - d_s) <= 0.065
                            if ov >= 0.35 * n_dur or near_onset:
                                pc_diff = abs(n.pitch - d_p) % 12
                                if is_other:
                                    # Reject only genuinely weak bleed from louder simultaneous guitar/vocals
                                    # (strong on-beat arpeggio/fiddle notes in 'other' with vel >= 55 are preserved)
                                    if pc_diff == 0 and n.velocity < 55 and d_v >= n.velocity + 12:
                                        is_bleed = True
                                        break
                                    if d_tag == "guitar" and pc_diff == 7 and n.velocity < 52 and d_v >= n.velocity + 15:
                                        is_bleed = True
                                        break
                                elif is_piano and d_tag == "vocals":
                                    if pc_diff == 0 and n.velocity < 55 and d_v >= n.velocity + 12:
                                        is_bleed = True
                                        break
                        if not is_bleed:
                            debleeded.append(n)
                    # Keep debleeded notes if at least 12 notes remain, otherwise keep top-velocity notes
                    if len(debleeded) >= 12:
                        clean_notes = debleeded

            # 3. Instrument-Specific Acoustic & Register Conditioning
            events = []
            beat_sec = 60.0 / max(tempo_bpm, 40.0)

            if is_drum:
                # Group drum hits within 45ms and map to standard 3-piece Percussion Clef notation:
                # Kick (36) -> F4 (65), Snare (38) -> C5 (72), Hi-Hat (42) -> G5 (79)
                drum_map = {36: 65, 35: 65, 38: 72, 40: 72, 42: 79, 46: 79, 49: 79}
                sorted_notes = sorted(inst.notes, key=lambda x: x.start)
                clusters = []
                for n in sorted_notes:
                    mapped_p = drum_map.get(n.pitch, 72)
                    if not clusters or (n.start - clusters[-1]["start"] > 0.045):
                        clusters.append({"start": n.start, "end": n.start + 0.22, "pitches": [mapped_p]})
                    else:
                        if mapped_p not in clusters[-1]["pitches"]:
                            clusters[-1]["pitches"].append(mapped_p)
                for c in clusters:
                    events.append({"start": c["start"], "end": c["end"], "pitches": sorted(c["pitches"])[:2]})

            elif is_bass:
                # Bass: Monophonic attack-sustain octave merger + Viterbi octave continuity + 8vb Bass Staff placement
                sorted_notes = sorted(clean_notes, key=lambda x: x.start)
                merged_bass = []
                for n in sorted_notes:
                    # Fold into sounding bass octave [31 (G1), 47 (B2)]
                    norm_p = self._fold_pitch_to_window(n.pitch, 31, 47)
                    if not merged_bass:
                        merged_bass.append({"start": n.start, "end": n.end, "pitch": norm_p, "vel": n.velocity})
                        continue
                    prev = merged_bass[-1]
                    is_same_pc = (norm_p % 12) == (prev["pitch"] % 12)
                    is_close = (n.start - prev["end"]) <= 0.16
                    if is_same_pc and is_close and abs(n.pitch - prev["pitch"]) in [11, 12, 13]:
                        prev["end"] = max(prev["end"], n.end)
                    elif n.start < prev["end"]:
                        if n.start > prev["start"] + 0.12:
                            prev["end"] = n.start
                            merged_bass.append({"start": n.start, "end": n.end, "pitch": norm_p, "vel": n.velocity})
                    else:
                        merged_bass.append({"start": n.start, "end": n.end, "pitch": norm_p, "vel": n.velocity})

                # Standard 8vb Bass Clef written transposition (+12 semitones -> [43 (G2), 59 (B3)])
                for b in merged_bass:
                    written_p = self._fold_pitch_to_window(b["pitch"] + 12, 43, 59)
                    events.append({
                        "start": b["start"],
                        "end": b["end"],
                        "pitches": [written_p]
                    })

            elif is_guitar:
                # Guitar: Filter acoustic bounds [40 (E2), 76 (E5)], consolidate 45ms strums,
                # voice chords in close position inside Treble Staff [57 (A3), 76 (E5)], and merge off-beat decay tails
                valid_notes = [n for n in clean_notes if 38 <= n.pitch <= 78 and not (n.velocity < 45 and (n.end - n.start) < 0.12)]
                sorted_notes = sorted(valid_notes, key=lambda x: x.start)
                chords = []
                for n in sorted_notes:
                    if not chords or (n.start - chords[-1]["start"] > 0.045):
                        chords.append({"start": n.start, "end": n.end, "pitches": [n.pitch], "max_vel": n.velocity})
                    else:
                        chords[-1]["pitches"].append(n.pitch)
                        chords[-1]["end"] = max(chords[-1]["end"], n.end)
                        chords[-1]["max_vel"] = max(chords[-1]["max_vel"], n.velocity)

                # Merge weak string-decay sub-events ONLY when they do not land on a beat boundary!
                consolidated = []
                for c in chords:
                    voiced = self._voice_polyphonic_chord(c["pitches"], target_low=57, target_high=76, max_voices=3)
                    if not voiced:
                        continue
                    if consolidated:
                        prev = consolidated[-1]
                        prev_pcs = {p % 12 for p in prev["pitches"]}
                        curr_pcs = {p % 12 for p in voiced}
                        gap = c["start"] - prev["start"]
                        rel_b = (c["start"] - t0) / beat_sec
                        is_near_beat = abs(rel_b - round(rel_b)) <= 0.22
                        if not is_near_beat and gap < 0.16 and curr_pcs.issubset(prev_pcs) and len(voiced) <= len(prev["pitches"]) and c["max_vel"] <= prev["max_vel"] * 0.85:
                            prev["end"] = max(prev["end"], c["end"])
                            continue
                    consolidated.append({"start": c["start"], "end": c["end"], "pitches": voiced, "max_vel": c["max_vel"]})

                events = [{"start": c["start"], "end": c["end"], "pitches": c["pitches"]} for c in consolidated]

            elif is_vocal or is_other:
                # Vocals & Other (Lead Strings / Fiddle / Synth Counter-Melody):
                # Strictly monophonic single-voice line inside Treble Staff [55 (G3), 79 (G5)]
                # Eliminates 100% of false cross-stem bleed chord stacks!
                low_w, high_w = (57, 79) if is_other else (55, 79)
                valid_mono = [
                    n for n in clean_notes
                    if (n.pitch >= 52 if is_other else True) and n.velocity >= (46 if is_other else 40)
                ]
                sorted_notes = sorted(valid_mono, key=lambda x: (x.start, -x.velocity))
                for n in sorted_notes:
                    vp = self._fold_pitch_to_window(n.pitch, low_w, high_w)
                    if not events:
                        events.append({"start": n.start, "end": n.end, "pitches": [vp], "vel": n.velocity})
                    else:
                        prev = events[-1]
                        # Simultaneous overtone/bleed within 65ms: keep stronger velocity note
                        if abs(n.start - prev["start"]) < 0.065:
                            if n.velocity > prev.get("vel", 0):
                                prev["pitches"] = [vp]
                                prev["end"] = max(prev["end"], n.end)
                                prev["vel"] = n.velocity
                            continue
                        if n.start < prev["end"]:
                            prev["end"] = max(prev["start"] + 0.05, n.start)
                        if n.start >= prev["end"]:
                            events.append({"start": n.start, "end": n.end, "pitches": [vp], "vel": n.velocity})

            else:
                # Piano / Keys: Single-staff Treble Clef close-position voicing inside [57 (A3), 77 (F5)]
                valid_notes = [n for n in clean_notes if n.velocity >= 42]
                sorted_notes = sorted(valid_notes, key=lambda x: x.start)
                chords = []
                for n in sorted_notes:
                    if not chords or (n.start - chords[-1]["start"] > 0.045):
                        chords.append({"start": n.start, "end": n.end, "pitches": [n.pitch], "max_vel": n.velocity})
                    else:
                        chords[-1]["pitches"].append(n.pitch)
                        chords[-1]["end"] = max(chords[-1]["end"], n.end)
                        chords[-1]["max_vel"] = max(chords[-1]["max_vel"], n.velocity)

                for c in chords:
                    voiced = self._voice_polyphonic_chord(c["pitches"], target_low=57, target_high=77, max_voices=3)
                    if voiced:
                        events.append({"start": c["start"], "end": c["end"], "pitches": voiced})

            # 4. Harmonized Song Key Signature
            if is_drum:
                detected_key = music21.key.KeySignature(0)
            else:
                detected_key = master_key_sig
                if not detected_key:
                    detected_key = music21.key.Key(key_tonic)

            # 5. Beat-Locked 8th-Note Metric Quantization (Grid = 0.5 beat)
            grid = 0.5  # Strict 8th-note grid guarantees zero 16th-rest clutter and zero double-dotted notes

            raw_quantized = []
            for ev in events:
                rel_start = max(0.0, (ev["start"] - t0) / beat_sec)
                raw_dur = (ev["end"] - ev["start"]) / beat_sec
                q_start = round(rel_start / grid) * grid
                q_dur = max(grid, round(raw_dur / grid) * grid)
                if is_drum:
                    q_dur = 0.5
                raw_quantized.append({"start": q_start, "dur": q_dur, "pitches": ev["pitches"]})

            # Deduplicate identical q_start offsets so two events never collide at the same beat offset!
            quantized = []
            for ev in sorted(raw_quantized, key=lambda x: x["start"]):
                if not quantized or ev["start"] > quantized[-1]["start"]:
                    quantized.append(ev)
                else:
                    prev = quantized[-1]
                    if is_mono:
                        if ev["dur"] > prev["dur"]:
                            prev["pitches"] = ev["pitches"]
                        prev["dur"] = max(prev["dur"], ev["dur"])
                    else:
                        combined = sorted(list(set(prev["pitches"] + ev["pitches"])))
                        prev["pitches"] = self._voice_polyphonic_chord(combined, target_low=57, target_high=76, max_voices=3) if not is_drum else combined[:2]
                        prev["dur"] = max(prev["dur"], ev["dur"])

            # Enforce non-overlapping sequential flow and smooth legato breath gaps
            for idx in range(len(quantized) - 1):
                curr = quantized[idx]
                nxt = quantized[idx + 1]
                if curr["start"] + curr["dur"] > nxt["start"]:
                    curr["dur"] = max(0.5, nxt["start"] - curr["start"])
                gap = nxt["start"] - (curr["start"] + curr["dur"])
                if not is_drum and gap == 0.5 and curr["dur"] >= 1.0:
                    # Connect tiny half-beat breath gaps on sustained notes for cleaner reading
                    curr["dur"] += 0.5

            # Key-Locked Diatonic Pitch Purification:
            # Snap non-diatonic chromatic bleed/scoop notes into the active key scale so scores never contain wrong out-of-key harmonies.
            if not is_drum and len(quantized) >= 1:
                diatonic_pcs = self._get_diatonic_pcs(detected_key)
                for idx, ev in enumerate(quantized):
                    neighbors = []
                    if idx + 1 < len(quantized) and (quantized[idx + 1]["start"] - (ev["start"] + ev["dur"])) <= 2.0:
                        neighbors.extend(quantized[idx + 1]["pitches"])
                    if idx - 1 >= 0 and (ev["start"] - (quantized[idx - 1]["start"] + quantized[idx - 1]["dur"])) <= 2.0:
                        neighbors.extend(quantized[idx - 1]["pitches"])
                    snapped = []
                    for p in ev["pitches"]:
                        if (p % 12) not in diatonic_pcs:
                            diatonic_adj = [np_p for np_p in neighbors if (np_p % 12) in diatonic_pcs and abs(np_p - p) == 1]
                            if diatonic_adj:
                                snapped.append(diatonic_adj[0])
                            elif ev["dur"] <= 1.5 or is_other or is_guitar or is_piano:
                                # Snap to nearest diatonic scale degree (+1 or -1 semitone)
                                if ((p + 1) % 12) in diatonic_pcs:
                                    snapped.append(p + 1)
                                elif ((p - 1) % 12) in diatonic_pcs:
                                    snapped.append(p - 1)
                                else:
                                    snapped.append(p)
                            else:
                                snapped.append(p)
                        else:
                            snapped.append(p)
                    ev["pitches"] = sorted(list(set(snapped)))

            # Polyphonic Beat-Pair Consolidation: merge identical 0.5+0.5 chord re-triggers on the same beat into a 1.0 quarter note
            if not is_mono and not is_drum and len(quantized) >= 2:
                consolidated_q = []
                idx = 0
                while idx < len(quantized):
                    curr = quantized[idx]
                    if (
                        idx + 1 < len(quantized)
                        and curr["dur"] == 0.5
                        and quantized[idx + 1]["dur"] == 0.5
                        and round(curr["start"] % 1.0, 2) == 0.0
                        and round(quantized[idx + 1]["start"] - curr["start"], 2) == 0.5
                        and curr["pitches"] == quantized[idx + 1]["pitches"]
                    ):
                        consolidated_q.append({"start": curr["start"], "dur": 1.0, "pitches": curr["pitches"]})
                        idx += 2
                    else:
                        consolidated_q.append(curr)
                        idx += 1
                quantized = consolidated_q

            default_bar_q = {"2/4": 2.0, "3/4": 3.0, "6/8": 3.0, "4/4": 4.0, "5/4": 5.0, "6/4": 6.0, "7/4": 7.0}.get(time_sig_str, 4.0)
            max_q = max((ev["start"] + ev["dur"] for ev in quantized), default=default_bar_q)

            # Build per-measure meter map covering [0.0, max_q]
            active_meters = list(measure_meters) if measure_meters else [(default_bar_q, time_sig_str)]
            cum_q = sum(m_q for m_q, _ in active_meters)
            while cum_q < max_q:
                last_m_q, last_ts = active_meters[-1]
                active_meters.append((last_m_q, last_ts))
                cum_q += last_m_q

            # Trim trailing measures beyond max_q while keeping at least 1 measure
            trimmed_meters = []
            running_q = 0.0
            for m_q, m_ts in active_meters:
                trimmed_meters.append((m_q, m_ts))
                running_q += m_q
                if running_q >= max_q:
                    break
            active_meters = trimmed_meters if trimmed_meters else [(default_bar_q, time_sig_str)]
            total_measures = len(active_meters)

            measure_bounds = []
            cur_b = 0.0
            for m_q, m_ts in active_meters:
                measure_bounds.append((round(cur_b, 2), round(cur_b + m_q, 2), m_q, m_ts))
                cur_b += m_q

            # Beat-1 Downbeat Lock: eliminate lone 0.5 eighth-rest jitter on Beat 1 caused by soft attack lag
            for b_start, b_end, _, _ in measure_bounds:
                has_downbeat = any(abs(ev["start"] - b_start) < 0.05 for ev in quantized)
                has_tie_over = any(ev["start"] < b_start and (ev["start"] + ev["dur"] - b_start) > 0.5 for ev in quantized)
                if not has_downbeat and not has_tie_over:
                    for ev in quantized:
                        if abs(ev["start"] - (b_start + 0.5)) < 0.05:
                            ev["start"] = b_start
                            ev["dur"] = round(ev["dur"] + 0.5, 2)
                            break

            # 6. Distribute notes into variable-meter measures with Canonical Decomposition
            measure_events = {m: [] for m in range(1, total_measures + 1)}

            for ev in quantized:
                q_s = ev["start"]
                q_d = ev["dur"]
                p = ev["pitches"]

                # Locate starting measure m_idx (1-indexed)
                m_idx = total_measures
                for idx_m, (b_start, b_end, _, _) in enumerate(measure_bounds):
                    if b_start <= q_s < b_end:
                        m_idx = idx_m + 1
                        break

                b_start, b_end, bar_q, ts_m = measure_bounds[m_idx - 1]
                offset_in_m = round((q_s - b_start) * 2.0) / 2.0
                spill = round(((offset_in_m + q_d) - bar_q) * 2.0) / 2.0

                # Suppress short reverb/bleed spillover (<= 0.5 beat) across barlines
                if spill <= 0.5:
                    dur_in_m = min(q_d, round(bar_q - offset_in_m, 2))
                    segs = self._decompose_note_interval(offset_in_m, offset_in_m + dur_in_m, tie_in=False, tie_out=False, time_sig_str=ts_m)
                    for off, d, t_val in segs:
                        measure_events[m_idx].append({"offset": off, "dur": d, "pitches": p, "tie": t_val})
                else:
                    # Genuinely held note crossing barline
                    segs_m1 = self._decompose_note_interval(offset_in_m, bar_q, tie_in=False, tie_out=True, time_sig_str=ts_m)
                    for off, d, t_val in segs_m1:
                        measure_events[m_idx].append({"offset": off, "dur": d, "pitches": p, "tie": t_val})

                    if m_idx + 1 <= total_measures:
                        _, _, next_bar_q, next_ts = measure_bounds[m_idx]
                        dur_m2 = min(next_bar_q, round(spill * 2.0) / 2.0)
                        if dur_m2 >= 0.5:
                            segs_m2 = self._decompose_note_interval(0.0, dur_m2, tie_in=True, tie_out=False, time_sig_str=next_ts)
                            for off, d, t_val in segs_m2:
                                measure_events[m_idx + 1].append({"offset": off, "dur": d, "pitches": p, "tie": t_val})

            # 7. Construct music21 Part with Dynamic Section Time Signatures, Canonical Rests & Automatic Beaming
            new_part = music21.stream.Part()
            new_part.id = 'P1'
            new_part.partName = ''

            if is_bass:
                part_clef = music21.clef.BassClef()
            elif is_drum:
                part_clef = music21.clef.PercussionClef()
            else:
                part_clef = music21.clef.TrebleClef()

            tempo_mark = music21.tempo.MetronomeMark(number=round(tempo_bpm))
            key_sharps = int(getattr(detected_key, 'sharps', 0) or 0)
            prev_ts = None

            for m_num in range(1, total_measures + 1):
                m = music21.stream.Measure(number=m_num)
                _, _, bar_q, ts_m = measure_bounds[m_num - 1]

                if m_num == 1:
                    m.insert(0, part_clef)
                    m.insert(0, detected_key)
                    m.insert(0, music21.meter.TimeSignature(ts_m))
                    m.insert(0, tempo_mark)
                    prev_ts = ts_m
                elif ts_m != prev_ts:
                    m.insert(0, music21.meter.TimeSignature(ts_m))
                    prev_ts = ts_m

                # Deduplicate any overlap caused by barline tie-ins
                raw_evs = sorted(measure_events[m_num], key=lambda x: x["offset"])
                evs = []
                for e in raw_evs:
                    if not evs:
                        evs.append(e)
                    else:
                        prev = evs[-1]
                        if e["offset"] < round(prev["offset"] + prev["dur"], 2):
                            avail = round(e["offset"] - prev["offset"], 2)
                            if avail >= 0.5:
                                prev["dur"] = avail
                                evs.append(e)
                        else:
                            evs.append(e)

                if not evs:
                    for r_off, r_dur in self._decompose_rest_interval(0.0, bar_q, time_sig_str=ts_m):
                        m.insert(r_off, music21.note.Rest(quarterLength=r_dur))
                else:
                    curr_pos = 0.0
                    for ev in evs:
                        if ev["offset"] > curr_pos:
                            for r_off, r_dur in self._decompose_rest_interval(curr_pos, ev["offset"], time_sig_str=ts_m):
                                m.insert(r_off, music21.note.Rest(quarterLength=r_dur))

                        unique_p = sorted(list(set(ev["pitches"])))
                        if len(unique_p) == 1 or is_mono:
                            pitch_val = unique_p[0] if is_bass else unique_p[-1]
                            spelled_p = self._midi_to_spelled_pitch(pitch_val, key_sharps)
                            el = music21.note.Note(spelled_p, quarterLength=ev["dur"])
                        else:
                            spelled_pitches = [self._midi_to_spelled_pitch(pv, key_sharps) for pv in unique_p]
                            el = music21.chord.Chord(spelled_pitches, quarterLength=ev["dur"])

                        if ev["tie"]:
                            el.tie = music21.tie.Tie(ev["tie"])

                        m.insert(ev["offset"], el)
                        curr_pos = round(ev["offset"] + ev["dur"], 2)

                    if curr_pos < bar_q:
                        for r_off, r_dur in self._decompose_rest_interval(curr_pos, bar_q, time_sig_str=ts_m):
                            m.insert(r_off, music21.note.Rest(quarterLength=r_dur))

                new_part.append(m)

            # Automatically beam eighth notes within each beat across the entire Part!
            try:
                new_part.makeBeams(inPlace=True)
            except Exception as beam_err:
                self.logger.warning(f"Beaming warning: {beam_err}")

            # Optimize accidentals: eliminate redundant naturals and duplicate measure sharps
            if not is_drum:
                new_part.makeAccidentals(
                    inPlace=True,
                    cautionaryPitchClass=False,
                    cautionaryAll=False,
                    cautionaryNotImmediateRepeat=False
                )
            else:
                for el in new_part.recurse().notes:
                    for p_obj in el.pitches:
                        p_obj.accidental = None

            # 8. Wrap in Score with clean metadata
            clean_score = music21.stream.Score()
            clean_score.metadata = music21.metadata.Metadata()
            clean_score.metadata.title = None
            clean_score.metadata.movementName = None
            clean_score.metadata.composer = None
            clean_score.insert(0, new_part)

            clean_score.write('musicxml', fp=str(output_xml_path))

            # 9. Post-process XML: strip placeholder metadata and enforce clean multi-rest / system spacing
            xml_content = output_xml_path.read_text(encoding='utf-8')
            xml_content = re.sub(r'\s*<movement-title>.*?</movement-title>', '', xml_content)
            xml_content = re.sub(r'\s*<creator.*?>.*?</creator>', '', xml_content)
            xml_content = xml_content.replace('Music21 Fragment', '').replace('Music21', '')
            output_xml_path.write_text(xml_content, encoding='utf-8')

            return output_xml_path

        except Exception as e:
            import traceback
            self.logger.error(f"MusicXML conversion failed: {e}\n{traceback.format_exc()}")
            raise e
