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
            if midi_paths:
                opt_bpm, opt_t0 = self._optimize_click_track(midi_paths, tempo)
                tempo = opt_bpm
                t0 = opt_t0

                # Refine Key Signature using symbolic MIDI pitch-class duration fit to minimize accidentals
                from collections import Counter
                pcs_dur = Counter()
                for mp in midi_paths:
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

            self.logger.info(f"Detected Click Track: Tempo={tempo:.1f} BPM, Downbeat t0={t0:.3f}s, Key={key_note}")
            self._song_cache[cache_key] = (tempo, key_note, t0)
            return tempo, key_note, t0

        except Exception as e:
            self.logger.warning(f"Attribute detection fallback: {e}")
            return 120.0, "C", 0.0

    def _optimize_click_track(self, midi_paths: list, init_bpm: float):
        """
        Finds the exact studio click-track (BPM, downbeat t0) that maximizes
        phase-locking of note onsets to the 4/4 metric grid.
        """
        onsets = []
        weights = []
        bar_weights = []

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
                    # Long bass/chord notes strongly anchor Beat 1 of the measure
                    bar_weights.append(w * (4.0 if (is_rhythm and dur >= 0.7) else 0.5))
            except Exception:
                continue

        if len(onsets) < 8:
            return round(init_bpm), 0.0

        onsets = np.array(onsets)
        weights = np.array(weights)
        weights /= np.sum(weights)
        bar_weights = np.array(bar_weights)
        bar_weights /= np.sum(bar_weights)

        first_onset = float(np.percentile(onsets, 1)) if len(onsets) > 30 else float(np.min(onsets))
        earliest = float(np.min(onsets))

        best_score = -1e9
        best_bpm = round(init_bpm)
        best_t0 = earliest

        # Search integer BPMs around initial acoustic estimate
        low_bpm = max(65, int(round(init_bpm)) - 4)
        high_bpm = min(185, int(round(init_bpm)) + 5)

        for bpm_cand in range(low_bpm, high_bpm + 1):
            beat_sec = 60.0 / float(bpm_cand)
            phases_beat = 2.0 * np.pi * (onsets - earliest) / beat_sec
            phases_eighth = 4.0 * np.pi * (onsets - earliest) / beat_sec

            z_beat = np.sum(weights * np.exp(1j * phases_beat))
            z_eighth = np.sum(weights * np.exp(1j * phases_eighth))

            # Slight prior favoring proximity to acoustic tempo
            prior = 1.0 - 0.015 * abs(bpm_cand - init_bpm)
            score = (np.abs(z_beat) * 1.0 + np.abs(z_eighth) * 0.55) * prior

            if score > best_score:
                best_score = score
                best_bpm = float(bpm_cand)
                angle = float(np.angle(z_beat))
                beat_phase = earliest + (angle / (2.0 * np.pi)) * beat_sec
                while beat_phase > earliest + 0.2 * beat_sec:
                    beat_phase -= beat_sec
                while beat_phase < 0.0:
                    beat_phase += beat_sec
                best_t0 = beat_phase

        # Determine which of the 4 beat phases aligns best with 4/4 measure downbeats
        beat_sec = 60.0 / best_bpm
        best_bar_t0 = best_t0
        best_bar_score = -1e9
        for m_shift in range(4):
            cand_t0 = best_t0 - m_shift * beat_sec
            while cand_t0 < -3.5 * beat_sec:
                cand_t0 += 4.0 * beat_sec
            bar_phases = 2.0 * np.pi * (onsets - cand_t0) / (4.0 * beat_sec)
            bar_alignment = float(np.sum(bar_weights * np.cos(bar_phases)))
            if bar_alignment > best_bar_score:
                best_bar_score = bar_alignment
                best_bar_t0 = cand_t0

        # Keep t0 non-negative or within 1 measure before the first onset
        while best_bar_t0 > earliest + 0.25 * beat_sec:
            best_bar_t0 -= 4.0 * beat_sec
        while best_bar_t0 < -3.75 * beat_sec:
            best_bar_t0 += 4.0 * beat_sec

        return best_bpm, best_bar_t0

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
    def _decompose_rest_interval(start_q: float, end_q: float) -> list:
        """
        Decomposes a silent interval [start_q, end_q] within a 4.0-beat measure
        strictly along the 4/4 metric hierarchy:
        - Full measure [0.0, 4.0] -> [4.0] (Whole rest)
        - Half measure [0.0, 2.0] or [2.0, 4.0] -> [2.0] (Half rest)
        - Full beat [k, k+1] -> [1.0] (Quarter rest)
        - Half beat [k, k+0.5] or [k+0.5, k+1] -> [0.5] (Eighth rest)
        Guarantees ZERO dotted rests and ZERO rests crossing the half-bar!
        """
        a = round(start_q * 2.0) / 2.0
        b = round(end_q * 2.0) / 2.0
        if b <= a:
            return []
        if a == 0.0 and b == 4.0:
            return [(0.0, 4.0)]
        # Split across the half-bar (2.0)
        if a < 2.0 and b > 2.0:
            return (
                MusicProcessingService._decompose_rest_interval(a, 2.0) +
                MusicProcessingService._decompose_rest_interval(2.0, b)
            )
        # Inside Half 1 [0.0, 2.0] or Half 2 [2.0, 4.0]
        if (a == 0.0 and b == 2.0) or (a == 2.0 and b == 4.0):
            return [(a, 2.0)]
        mid_beat = 1.0 if b <= 2.0 else 3.0
        if a < mid_beat and b > mid_beat:
            return (
                MusicProcessingService._decompose_rest_interval(a, mid_beat) +
                MusicProcessingService._decompose_rest_interval(mid_beat, b)
            )
        return [(a, round(b - a, 2))]

    @staticmethod
    def _decompose_note_interval(start_q: float, end_q: float, tie_in: bool = False, tie_out: bool = False) -> list:
        """
        Decomposes a note/chord interval [start_q, end_q] inside a 4.0-beat measure into
        canonical engraving durations {4.0, 3.0, 2.0, 1.5, 1.0, 0.5}:
        - Eliminates double-dotted notes (3.5, 1.75) and awkward half-bar syncopations.
        - Returns list of (offset, dur, tie_type) tuples.
        """
        a = round(start_q * 2.0) / 2.0
        b = round(end_q * 2.0) / 2.0
        dur = round(b - a, 2)
        if dur <= 0:
            return []

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
            left = MusicProcessingService._decompose_note_interval(a, 2.0, tie_in=False, tie_out=False)
            right = MusicProcessingService._decompose_note_interval(2.0, b, tie_in=False, tie_out=False)
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
        - Locks all note timings to the song's true click-track (BPM, downbeat t0).
        - Enforces staff-centered tessitura and close-position chord voicing (zero skyscraper ledger lines).
        - Decomposes all notes and rests along the 4/4 metric hierarchy (zero dotted rests, zero double-dotted notes).
        - Applies automatic eighth-note beaming (makeBeams) per beat.
        """
        output_xml_path = self.output_dir / f"{output_name}.musicxml"
        self.logger.info(f"Converting MIDI to XML: {midi_path} -> {output_xml_path}")

        try:
            # 1. Detect Beat-Locked Click Track (BPM, Key, Downbeat t0)
            tempo_bpm = 120.0
            key_tonic = "C"
            t0 = 0.0
            if audio_ref_path and audio_ref_path.exists():
                res = self.detect_attributes(audio_ref_path, drum_ref_path)
                if len(res) == 3:
                    tempo_bpm, key_tonic, t0 = res
                else:
                    tempo_bpm, key_tonic = res

            name_lower = output_name.lower()
            is_vocal = any(m in name_lower for m in ["vocal", "voice"])
            is_bass = "bass" in name_lower
            is_guitar = "guitar" in name_lower
            is_drum = any(d in name_lower for d in ["drums", "drum", "percussion"])
            is_mono = is_vocal or is_bass

            # 2. Parse MIDI
            pm = pretty_midi.PrettyMIDI(str(midi_path))
            if not pm.instruments:
                raise ValueError("MIDI file contains no instrument tracks")

            inst = pm.instruments[0]

            clean_notes = [
                n for n in inst.notes
                if not (n.end - n.start < 0.08 and n.velocity < 40)
            ]

            # 3. Instrument-Specific Acoustic & Register Conditioning
            events = []

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
                # Guitar: Filter acoustic bounds [40 (E2), 76 (E5)], consolidate 60ms strums,
                # voice chords in close position inside Treble Staff [57 (A3), 76 (E5)], and merge decay tails
                valid_notes = [n for n in clean_notes if 38 <= n.pitch <= 78 and not (n.velocity < 45 and (n.end - n.start) < 0.12)]
                sorted_notes = sorted(valid_notes, key=lambda x: x.start)
                chords = []
                for n in sorted_notes:
                    if not chords or (n.start - chords[-1]["start"] > 0.065):
                        chords.append({"start": n.start, "end": n.end, "pitches": [n.pitch], "max_vel": n.velocity})
                    else:
                        chords[-1]["pitches"].append(n.pitch)
                        chords[-1]["end"] = max(chords[-1]["end"], n.end)
                        chords[-1]["max_vel"] = max(chords[-1]["max_vel"], n.velocity)

                # Merge weak string-decay sub-events into the main strum
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
                        # If a single-note decay of the same chord fires within 0.28s, absorb it into the strum duration
                        if gap < 0.28 and curr_pcs.issubset(prev_pcs) and len(voiced) <= len(prev["pitches"]) and c["max_vel"] <= prev["max_vel"] * 0.9:
                            prev["end"] = max(prev["end"], c["end"])
                            continue
                    consolidated.append({"start": c["start"], "end": c["end"], "pitches": voiced, "max_vel": c["max_vel"]})

                events = [{"start": c["start"], "end": c["end"], "pitches": c["pitches"]} for c in consolidated]

            elif is_vocal:
                # Vocals: Monophonic melody with tessitura clamped to [55 (G3), 79 (G5)]
                sorted_notes = sorted(clean_notes, key=lambda x: x.start)
                for n in sorted_notes:
                    vp = self._fold_pitch_to_window(n.pitch, 55, 79)
                    if not events:
                        events.append({"start": n.start, "end": n.end, "pitches": [vp]})
                    else:
                        prev = events[-1]
                        if n.start < prev["end"]:
                            prev["end"] = max(prev["start"] + 0.05, n.start)
                        if n.start >= prev["end"]:
                            events.append({"start": n.start, "end": n.end, "pitches": [vp]})

            else:
                # Piano / Other / Strings: Close-position voicing inside Treble Staff [57 (A3), 77 (F5)]
                valid_notes = [n for n in clean_notes if n.velocity >= 44]
                sorted_notes = sorted(valid_notes, key=lambda x: x.start)
                chords = []
                for n in sorted_notes:
                    if not chords or (n.start - chords[-1]["start"] > 0.065):
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
            beat_sec = 60.0 / max(tempo_bpm, 40.0)
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

            # Diatonic Scoop Smoothing: snap 0.5-beat 1-semitone vocal/instrumental scoops into adjacent diatonic notes
            if not is_drum and len(quantized) >= 2:
                diatonic_pcs = self._get_diatonic_pcs(detected_key)
                for idx, ev in enumerate(quantized):
                    if ev["dur"] > 0.5:
                        continue
                    neighbors = []
                    if idx + 1 < len(quantized) and (quantized[idx + 1]["start"] - (ev["start"] + ev["dur"])) <= 2.0:
                        neighbors.extend(quantized[idx + 1]["pitches"])
                    if idx - 1 >= 0 and (ev["start"] - (quantized[idx - 1]["start"] + quantized[idx - 1]["dur"])) <= 2.0:
                        neighbors.extend(quantized[idx - 1]["pitches"])
                    if not neighbors:
                        continue
                    snapped = []
                    for p in ev["pitches"]:
                        if (p % 12) not in diatonic_pcs:
                            diatonic_adj = [np_p for np_p in neighbors if (np_p % 12) in diatonic_pcs and abs(np_p - p) == 1]
                            if diatonic_adj:
                                snapped.append(diatonic_adj[0])
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

            max_q = max((ev["start"] + ev["dur"] for ev in quantized), default=4.0)
            total_measures = max(1, int(np.ceil(max_q / 4.0)))

            # 6. Distribute notes into mathematically exact 4.0-beat measures with Canonical Decomposition
            measure_events = {m: [] for m in range(1, total_measures + 1)}

            for ev in quantized:
                q_s = ev["start"]
                q_d = ev["dur"]
                p = ev["pitches"]
                m_idx = int(q_s // 4.0) + 1
                offset_in_m = round((q_s % 4.0) * 2.0) / 2.0
                spill = round(((offset_in_m + q_d) - 4.0) * 2.0) / 2.0

                # Suppress short reverb/bleed spillover (<= 0.5 beat) across barlines
                if spill <= 0.5:
                    dur_in_m = min(q_d, round(4.0 - offset_in_m, 2))
                    segs = self._decompose_note_interval(offset_in_m, offset_in_m + dur_in_m, tie_in=False, tie_out=False)
                    for off, d, t_val in segs:
                        measure_events[m_idx].append({"offset": off, "dur": d, "pitches": p, "tie": t_val})
                else:
                    # Genuinely held note crossing barline
                    segs_m1 = self._decompose_note_interval(offset_in_m, 4.0, tie_in=False, tie_out=True)
                    for off, d, t_val in segs_m1:
                        measure_events[m_idx].append({"offset": off, "dur": d, "pitches": p, "tie": t_val})

                    dur_m2 = min(4.0, round(spill * 2.0) / 2.0)
                    if m_idx + 1 <= total_measures and dur_m2 >= 0.5:
                        segs_m2 = self._decompose_note_interval(0.0, dur_m2, tie_in=True, tie_out=False)
                        for off, d, t_val in segs_m2:
                            measure_events[m_idx + 1].append({"offset": off, "dur": d, "pitches": p, "tie": t_val})

            # 7. Construct music21 Part with Canonical Rests & Automatic Beaming
            new_part = music21.stream.Part()
            new_part.id = 'P1'
            new_part.partName = ''

            if is_bass:
                part_clef = music21.clef.BassClef()
            elif is_drum:
                part_clef = music21.clef.PercussionClef()
            else:
                part_clef = music21.clef.TrebleClef()

            time_sig = music21.meter.TimeSignature('4/4')
            tempo_mark = music21.tempo.MetronomeMark(number=round(tempo_bpm))
            key_sharps = int(getattr(detected_key, 'sharps', 0) or 0)

            for m_num in range(1, total_measures + 1):
                m = music21.stream.Measure(number=m_num)

                if m_num == 1:
                    m.insert(0, part_clef)
                    m.insert(0, detected_key)
                    m.insert(0, time_sig)
                    m.insert(0, tempo_mark)

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
                    m.insert(0.0, music21.note.Rest(quarterLength=4.0))
                else:
                    curr_pos = 0.0
                    for ev in evs:
                        if ev["offset"] > curr_pos:
                            for r_off, r_dur in self._decompose_rest_interval(curr_pos, ev["offset"]):
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

                    if curr_pos < 4.0:
                        for r_off, r_dur in self._decompose_rest_interval(curr_pos, 4.0):
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
