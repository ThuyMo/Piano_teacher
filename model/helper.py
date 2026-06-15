import re
from pathlib import Path
from typing import Optional, Tuple

import mido
import pandas as pd
from music21 import converter as m21_converter


_NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

_ROOT_TO_SEMITONE = {
    'C': 0, 'C#': 1, 'D-': 1,
    'D': 2, 'D#': 3, 'E-': 3,
    'E': 4,
    'F': 5, 'F#': 6, 'G-': 6,
    'G': 7, 'G#': 8, 'A-': 8,
    'A': 9, 'A#': 10, 'B-': 10,
    'B': 11,
}


def _pitch_name(pitch: int) -> str:
    return f"{_NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


def _collect_notes(mid: mido.MidiFile) -> list:
    """Parse all tracks into a flat list of {pitch, start, end} dicts (seconds)."""
    tpb = mid.ticks_per_beat
    events = []
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            events.append((tick, msg))
    events.sort(key=lambda x: x[0])

    notes, pending = [], {}
    tempo, last_tick, last_sec = 500_000, 0, 0.0

    for abs_tick, msg in events:
        now = last_sec + (abs_tick - last_tick) * tempo / tpb / 1_000_000
        if msg.type == 'set_tempo':
            last_tick, last_sec, tempo = abs_tick, now, msg.tempo
        elif msg.type == 'note_on' and msg.velocity > 0:
            pending[msg.note] = now
        elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            if msg.note in pending:
                notes.append({'pitch': msg.note, 'start': pending.pop(msg.note), 'end': now})

    return sorted(notes, key=lambda n: n['start'])


def mid_to_str(midi_path: str) -> str:
    """
    Convert a MIDI file to a compact text representation suitable for LLM input.

    Each line represents a time step:
        [T=<seconds>] <note>(<duration>s) ...

    Simultaneous notes (within 50 ms) are grouped on the same line.

    Example output:
        [T=0.00] C4(0.50s) E4(0.50s) G4(0.50s)
        [T=0.50] D4(0.25s) F4(0.25s)
    """
    mid = mido.MidiFile(midi_path)
    notes = _collect_notes(mid)

    # Group simultaneous notes (tolerance 50 ms)
    TOL = 0.05
    groups, i = [], 0
    while i < len(notes):
        t = notes[i]['start']
        grp = []
        while i < len(notes) and notes[i]['start'] - t <= TOL:
            grp.append(notes[i])
            i += 1
        groups.append((t, grp))

    lines = []
    for t, grp in groups:
        parts = ' '.join(
            f"{_pitch_name(n['pitch'])}({n['end'] - n['start']:.2f}s)"
            for n in sorted(grp, key=lambda n: n['pitch'])
        )
        lines.append(f"[T={t:.2f}] {parts}")

    return '\n'.join(lines)


def chord_detector(midi_path: str) -> Tuple[str, str]:
    """
    Detect the musical key of a MIDI file using the Krumhansl-Schmuckler algorithm.

    Returns:
        (tonic, mode) — e.g. ('G', 'major') or ('A', 'minor')
    """
    score = m21_converter.parse(midi_path)
    key = score.analyze('key')
    return key.tonic.name, key.mode


def transpose(
    midi_path: str,
    target: str = 'C',
    output_path: Optional[str] = None,
) -> Path:
    """
    Transpose a MIDI file to C major (target='C') or A minor (target='Am').

    The shift is chosen to be minimal (between -6 and +6 semitones) so the
    piece stays in a similar register.

    Args:
        midi_path:   Path to the source MIDI file.
        target:      'C' for C major, 'Am' for A minor.
        output_path: Destination path. Defaults to <stem>_transposed.mid next
                     to the source file.

    Returns:
        Path of the saved (or untouched) MIDI file.
    """
    tonic, _ = chord_detector(midi_path)

    target_root = 9 if target == 'Am' else 0  # A=9, C=0
    current_root = _ROOT_TO_SEMITONE.get(tonic, 0)

    # Minimal shift in [-6, +6]
    shift = (target_root - current_root + 6) % 12 - 6

    if shift == 0:
        return Path(midi_path)

    mid = mido.MidiFile(midi_path)
    for track in mid.tracks:
        for msg in track:
            if msg.type in ('note_on', 'note_off'):
                msg.note = max(0, min(127, msg.note + shift))

    if output_path is None:
        p = Path(midi_path)
        output_path = p.parent / f"{p.stem}_transposed{p.suffix}"

    out = Path(output_path)
    mid.save(str(out))
    return out

_NAME_TO_SEMITONE = {
    'C': 0, 'C#': 1, 'D': 2, 'D#': 3, 'E': 4,
    'F': 5, 'F#': 6, 'G': 7, 'G#': 8, 'A': 9, 'A#': 10, 'B': 11,
}

_NOTE_RE = re.compile(r'([A-G]#?)(-?\d+)\((\d+\.\d+)s\)')
_LINE_RE = re.compile(r'\[T=(\d+\.\d+)\]\s+(.+)')


def _name_to_pitch(name: str) -> int:
    m = re.match(r'([A-G]#?)(-?\d+)', name)
    return (int(m.group(2)) + 1) * 12 + _NAME_TO_SEMITONE[m.group(1)]


def str_to_mid(
    text: str,
    output_path: str,
    tempo: int = 500_000,
) -> Path:
    """
    Reconstruct a MIDI file from the text format produced by mid_to_str().

    Args:
        text:        String as returned by mid_to_str().
        output_path: Where to save the resulting .mid file.
        tempo:       Microseconds per beat (default 500 000 = 120 BPM).

    Returns:
        Path of the saved MIDI file.
    """
    TPB = 480

    def to_ticks(sec: float) -> int:
        return int(sec * TPB / tempo * 1_000_000)

    raw_events = []
    for line in text.strip().splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        t = float(m.group(1))
        for nm in _NOTE_RE.finditer(m.group(2)):
            pitch = _name_to_pitch(nm.group(1) + nm.group(2))
            dur = float(nm.group(3))
            raw_events.append((to_ticks(t), 'note_on', pitch, 64))
            raw_events.append((to_ticks(t + dur), 'note_off', pitch, 0))

    raw_events.sort(key=lambda x: x[0])

    mid = mido.MidiFile(ticks_per_beat=TPB)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage('set_tempo', tempo=tempo, time=0))

    prev_tick = 0
    for abs_tick, msg_type, pitch, velocity in raw_events:
        delta = abs_tick - prev_tick
        track.append(mido.Message(msg_type, note=pitch, velocity=velocity, time=delta))
        prev_tick = abs_tick

    out = Path(output_path)
    mid.save(str(out))
    return out


def mid_to_pd(midi_path: str) -> pd.DataFrame:
    """
    Convert a MIDI file to a pandas DataFrame for analysis.

    One row per note. Simultaneous notes (within 50 ms) share the same
    ``grouped_time``; each note keeps its own ``timestamp``.

    Columns:
        grouped_time  float  Anchor time of the chord group (seconds).
        note          str    Note name, e.g. 'C4', 'F#3'.
        timestamp     float  Actual note-on time (seconds).
        duration      float  Note duration (seconds).
        pitch         int    MIDI pitch number (0–127).
    """
    mid = mido.MidiFile(midi_path)
    notes = _collect_notes(mid)

    TOL = 0.05
    rows = []
    i = 0
    while i < len(notes):
        group_t = notes[i]['start']
        while i < len(notes) and notes[i]['start'] - group_t <= TOL:
            n = notes[i]
            rows.append({
                'grouped_time': group_t,
                'note':         _pitch_name(n['pitch']),
                'timestamp':    n['start'],
                'duration':     n['end'] - n['start'],
                'pitch':        n['pitch'],
            })
            i += 1

    return pd.DataFrame(rows, columns=['grouped_time', 'note', 'timestamp', 'duration', 'pitch'])


def pd_to_str(df: pd.DataFrame) -> str:
    """
    Convert a DataFrame produced by mid_to_pd() back to the mid_to_str() text format.

    Each chord group becomes one line:
        [T=<grouped_time>] <note>(<duration>s) ...

    Notes within each group are sorted by pitch (lowest first).
    """
    lines = []
    for group_t, group in df.groupby('grouped_time', sort=True):
        parts = ' '.join(
            f"{row['note']}({row['duration']:.2f}s)"
            for _, row in group.sort_values('pitch').iterrows()
        )
        lines.append(f"[T={group_t:.2f}] {parts}")
    return '\n'.join(lines)


if __name__ == "__main__":
    import sys
    result = transpose(sys.argv[1])
    print(f"{result}")

    # print(mid_to_pd(sys.argv[1]))
