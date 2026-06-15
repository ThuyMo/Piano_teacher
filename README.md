# Piano Teacher

A web app that turns any audio recording into a playable falling-notes piano game. Upload an MP3, wait for processing, and the right-hand melody becomes an interactive game driven by your MIDI keyboard.

---

## How it works — end to end

```
Audio file (MP3/WAV/…)
        │
        ▼
 ┌─────────────────────────────────────────────────────────┐
 │  Step 1  input_processor.py  ·  Audio → MIDI            │
 │  ffmpeg converts to mono 44 100 Hz WAV                  │
 │  transkun transcribes WAV to MIDI                        │
 └──────────────────────────┬──────────────────────────────┘
                             │  artifact/{stem}.mid
                             ▼
 ┌─────────────────────────────────────────────────────────┐
 │  Step 2  midi_processor.py  ·  Hand splitting            │
 │  Proximity-based algorithm assigns each note to RH / LH │
 │  Saves artifact/{stem}_RH.mid  and  _LH.mid             │
 └──────────────────────────┬──────────────────────────────┘
                             │  artifact/{stem}_RH.mid
                             ▼
 ┌─────────────────────────────────────────────────────────┐
 │  Step 3  helper.py  ·  Analysis                          │
 │  chord_detector  → detected key (e.g. "G major")        │
 │  mid_to_pd       → pandas DataFrame for stats           │
 │  Reports: note count, median note duration              │
 └──────────────────────────┬──────────────────────────────┘
                             │  metadata returned to UI
                             ▼
                    Game is ready to play
```

---

## Processing pipeline in detail

### Step 1 — `model/input_processor.py`

| Function | What it does |
|---|---|
| `convert_audio_to_midi(input_path)` | Calls `ffmpeg` to produce a mono 44 100 Hz 16-bit WAV, then pipes it through `transkun` (a neural piano transcription model) to produce a MIDI file saved in `artifact/`. |

### Step 2 — `model/midi_processor.py`

| Function | What it does |
|---|---|
| `split_midi_hands(input, rh_out, lh_out)` | Iterates notes in absolute-tick order. Each `note_on` is assigned to the hand whose last played pitch is closest (proximity heuristic). Skipped delta times are forwarded to the next kept event so timing is preserved exactly. |
| `extract_right_hand(midi_path)` | Thin wrapper: calls `split_midi_hands` and returns only the RH path. |

### Step 3 — `model/helper.py`

| Function | What it does |
|---|---|
| `chord_detector(midi_path)` | Loads the MIDI with music21 and runs the Krumhansl-Schmuckler algorithm to detect key and mode (e.g. `("G", "major")`). |
| `mid_to_pd(midi_path)` | Returns a pandas DataFrame with columns `grouped_time`, `note`, `timestamp`, `duration`, `pitch`. Simultaneous notes (within 50 ms) share a `grouped_time`. |
| `mid_to_str(midi_path)` | Converts MIDI to a compact LLM-friendly text format: `[T=0.00] C4(0.50s) E4(0.50s)`. |
| `pd_to_str(df)` | Converts the DataFrame back to the same text format. |
| `str_to_mid(text, output_path)` | Reconstructs a MIDI file from the text format. |
| `transpose(midi_path, target)` | Transposes to C major (`target='C'`) or A minor (`target='Am'`) with minimal semitone shift. |

---

## API endpoints — `app.py`

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Serves the dashboard (upload + file list). |
| `GET` | `/game` | Serves the piano game canvas. |
| `GET` | `/notes` | Returns `{ notes, total }` for the currently loaded MIDI. |
| `GET` | `/api/files` | Lists all `.mid` files in `artifact/` sorted by newest first. |
| `POST` | `/upload` | Accepts a multipart audio file, starts the pipeline in the background, returns `{ task_id }`. |
| `GET` | `/status/{task_id}` | Polls processing progress. Returns `{ status, step }` while running; `{ status:"done", file, key, notes, median_duration }` on success. |
| `POST` | `/load` | Body `{ "file": "name.mid" }`. Loads that file into the game state and resets score. |
| `WS` | `/ws` | Game loop WebSocket. Server pushes 30 fps state frames; client sends MIDI controller input. |

---

## User flow

```
1. Open http://localhost:8000
        │
        ▼
2. Dashboard — drag & drop (or browse) an audio file
        │
        ▼
3. Status bar shows live progress:
   "Uploading…"  →  "Converting audio to MIDI…"
                 →  "Splitting hands…"
                 →  "Analysing notes…"
        │
        ▼
4. Done banner appears:
   ✓ my_song_RH.mid · Key: G major · 320 notes · avg. 0.28s/note
   [▶ Play now]
        │
        ▼
5. Click ▶ Play now  (or ▶ Play on any file in the list below)
        │   POST /load  →  game state reset
        ▼
6. Piano game opens — falling notes scroll down toward the keyboard.
   Game pauses on each chord and waits for the player to press
   the correct keys on the connected MIDI keyboard before advancing.
        │
        ▼
7. Score is shown live. "Complete! Score: X / Y" at the end.
   Browser back button returns to the dashboard.
```

---

## Game mechanics

The game renders a canvas split into three zones:

```
┌─────────────────────────────┐  ← Header: score / chord prompt
│         FALL ZONE           │  ← Falling note bars (4-second lookahead)
│                             │
│      ══ HIT LINE ══         │  ← Notes must be played here
├─────────────────────────────┤
│         PIANO KEYS          │  ← Visual keyboard (C2 – B4)
└─────────────────────────────┘
```

| State | Behaviour |
|---|---|
| `PLAYING` | Game clock advances; note bars fall. |
| `WAITING` | Clock pauses at the current chord. Required keys highlighted in yellow. |
| `FINISHED` | Final score displayed. |

MIDI input from a connected keyboard is forwarded to the server over the WebSocket. The server validates pressed pitches against the required chord and advances the index on a correct match.

---

## Project structure

```
piano_game/
├── app.py                  # Main web server (dashboard + game)
├── server.py               # Standalone game server (CLI: python server.py file.mid)
├── model/
│   ├── input_processor.py  # Audio → MIDI  (ffmpeg + transkun)
│   ├── midi_processor.py   # Hand splitting
│   └── helper.py           # MIDI utilities + pandas helpers
├── static/
│   ├── dashboard.html      # Upload & file management UI
│   └── index.html          # Piano game canvas
├── artifact/               # Processed MIDI files (git-ignored)
└── uploads/                # Raw uploaded audio (git-ignored)
```

---

## Setup

```bash
pip install fastapi uvicorn mido music21 pandas

# Install system dependencies
brew install ffmpeg        # macOS
pip install transkun       # neural transcription model

python app.py
# Open http://localhost:8000
```
