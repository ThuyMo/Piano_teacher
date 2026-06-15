"""
Piano Teacher – main web app.
Usage: python app.py
Then open http://localhost:8000
"""
import asyncio
import json
import os
import queue
import re
import subprocess
import threading
import uuid
from pathlib import Path

import mido
import uvicorn
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from model.input_processor import convert_audio_to_midi
from model.midi_processor import extract_right_hand
from model.helper import chord_detector, mid_to_pd, pd_to_str, str_to_mid, transpose

BASE_DIR     = Path(__file__).parent
ARTIFACT_DIR = BASE_DIR / "artifact"
UPLOADS_DIR  = BASE_DIR / "uploads"
ARTIFACT_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)

app = FastAPI()
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# ─── MIDI helpers (mirrors server.py, no side-effects) ────────────────────────

def _load_notes(path: str) -> list:
    mid = mido.MidiFile(path)
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
    return sorted(notes, key=lambda x: x['start'])


def _group_notes(notes: list, tol: float = 0.05) -> list:
    groups, i = [], 0
    while i < len(notes):
        t = notes[i]['start']
        grp = []
        while i < len(notes) and notes[i]['start'] - t <= tol:
            grp.append(notes[i])
            i += 1
        groups.append({'time': t, 'notes': grp})
    return groups


# ─── Game state (single active game) ─────────────────────────────────────────

notes_data   = []
groups       = []
clients      = set()
midi_q       = queue.Queue()
active_notes = set()

g_time   = 0.0
g_status = 'PLAYING'
g_idx    = 0
g_score  = 0
g_hit    = set()


def _reset_game(path: str) -> None:
    global notes_data, groups, g_time, g_status, g_idx, g_score, g_hit
    notes_data = _load_notes(path)
    groups     = _group_notes(notes_data)
    g_time     = (groups[0]['time'] - 4.0) if groups else 0.0
    g_status   = 'PLAYING'
    g_idx      = 0
    g_score    = 0
    g_hit      = set()


# ─── yt-dlp helpers ───────────────────────────────────────────────────────────

def _yt_search(query: str) -> list:
    result = subprocess.run(
        ["yt-dlp", f"ytsearch5:{query} piano",
         "--dump-json", "--flat-playlist", "--quiet", "--no-warnings"],
        capture_output=True, text=True, timeout=30
    )
    entries = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        try:
            data = json.loads(line)
            video_id = data.get("id", "")
            if not video_id:
                continue
            entries.append({
                "id": video_id,
                "title": data.get("title", "Unknown"),
                "duration": data.get("duration"),
                "channel": data.get("channel") or data.get("uploader", ""),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return entries


def _download_preview(video_id: str, output_path: str) -> None:
    subprocess.run(
        ["yt-dlp", f"https://www.youtube.com/watch?v={video_id}",
         "--download-sections", "*0-30",
         "-x", "--audio-format", "mp3",
         "-o", output_path, "--quiet", "--no-warnings"],
        check=True, timeout=60
    )


def _download_audio(url: str, output_path: str) -> None:
    subprocess.run(
        ["yt-dlp", url, "-x", "--audio-format", "mp3",
         "-o", output_path, "--quiet", "--no-warnings"],
        check=True, timeout=300
    )


# ─── Background task tracking ────────────────────────────────────────────────

tasks: dict = {}  # task_id -> {"status": ..., ...}


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
async def dashboard():
    return FileResponse(BASE_DIR / "static" / "dashboard.html")


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


@app.get("/game")
async def game_page():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/notes")
async def get_notes():
    return JSONResponse({"notes": notes_data, "total": len(groups)})


@app.get("/api/files")
async def list_files():
    files = sorted(ARTIFACT_DIR.glob("*.mid"), key=lambda p: p.stat().st_mtime, reverse=True)
    return JSONResponse({
        "files": [{"name": f.name, "size": f.stat().st_size} for f in files]
    })


class LoadRequest(BaseModel):
    file: str

class DownloadRequest(BaseModel):
    url: str
    title: str = ""


@app.post("/load")
async def load_file(req: LoadRequest):
    path = ARTIFACT_DIR / req.file
    if not path.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)
    _reset_game(str(path))
    return JSONResponse({"ok": True})


async def _run_pipeline(input_path: Path, task_id: str) -> None:
    try:
        tasks[task_id]["step"] = "Converting audio to MIDI (ffmpeg + transkun)..."
        midi_path = await asyncio.to_thread(convert_audio_to_midi, str(input_path))

        tasks[task_id]["step"] = "Splitting hands..."
        rh_path = await asyncio.to_thread(extract_right_hand, str(midi_path))

        tasks[task_id]["step"] = "Detecting key and transposing..."
        tonic, mode = await asyncio.to_thread(chord_detector, str(rh_path))
        target = "Am" if mode == "minor" else "C"
        transposed_path = await asyncio.to_thread(
            transpose, str(rh_path), target,
            str(ARTIFACT_DIR / (rh_path.stem + "_transposed.mid"))
        )

        tasks[task_id]["step"] = "Processing notes for beginner..."
        df = await asyncio.to_thread(mid_to_pd, str(transposed_path))
        processed_df = df.groupby('grouped_time').apply(
            lambda x: x.loc[x['pitch'].idxmax()]
        ).reset_index(drop=True)
        processed_str = pd_to_str(processed_df)
        processed_path = ARTIFACT_DIR / (rh_path.stem + "_processed.mid")
        await asyncio.to_thread(str_to_mid, processed_str, str(processed_path))

        tasks[task_id] = {
            "status": "done",
            "file":   processed_path.name,
            "key":    f"{tonic} {mode}",
            "notes":  int(len(processed_df)),
            "median_duration": round(float(processed_df['duration'].median()), 3),
        }
    except Exception as exc:
        tasks[task_id] = {"status": "error", "error": str(exc)}


@app.post("/upload")
async def upload_audio(file: UploadFile = File(...)):
    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {"status": "processing", "step": "Uploading..."}
    content = await file.read()
    input_path = UPLOADS_DIR / file.filename
    input_path.write_bytes(content)
    asyncio.create_task(_run_pipeline(input_path, task_id))
    return JSONResponse({"task_id": task_id})


@app.get("/status/{task_id}")
async def task_status(task_id: str):
    return JSONResponse(tasks.get(task_id, {"status": "unknown"}))


@app.get("/api/search")
async def search_youtube(q: str):
    try:
        results = await asyncio.to_thread(_yt_search, q)
        return JSONResponse({"results": results})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/preview/{video_id}")
async def preview_audio(video_id: str):
    if not re.match(r'^[A-Za-z0-9_-]{11}$', video_id):
        return JSONResponse({"error": "Invalid video ID"}, status_code=400)
    cache_path = UPLOADS_DIR / f"preview_{video_id}.mp3"
    if not cache_path.exists():
        try:
            await asyncio.to_thread(_download_preview, video_id, str(cache_path))
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
    return FileResponse(str(cache_path), media_type="audio/mpeg")


@app.post("/api/download")
async def download_youtube(req: DownloadRequest):
    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {"status": "processing", "step": "Downloading from YouTube..."}

    async def pipeline():
        try:
            safe_title = re.sub(r'[^\w\s-]', '', req.title)[:40].strip() or task_id
            audio_path = UPLOADS_DIR / f"{safe_title}_{task_id}.mp3"
            tasks[task_id]["step"] = "Downloading audio from YouTube..."
            await asyncio.to_thread(_download_audio, req.url, str(audio_path))
        except Exception as exc:
            tasks[task_id] = {"status": "error", "error": str(exc)}
            return
        await _run_pipeline(audio_path, task_id)

    asyncio.create_task(pipeline())
    return JSONResponse({"task_id": task_id})


# ─── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_handler(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "midi":
                event_type = msg.get("event")
                note = int(msg.get("note"))
                velocity = int(msg.get("velocity", 0))
                if event_type == "note_on" and velocity > 0:
                    midi_q.put(mido.Message("note_on", note=note, velocity=velocity))
                elif event_type in {"note_off", "note_on"}:
                    midi_q.put(mido.Message("note_off", note=note, velocity=0))
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(websocket)


# ─── Game loop ────────────────────────────────────────────────────────────────

async def game_loop():
    global g_time, g_status, g_idx, g_score, g_hit
    last = asyncio.get_event_loop().time()

    while True:
        await asyncio.sleep(1 / 30)
        now = asyncio.get_event_loop().time()
        dt  = now - last
        last = now

        new_presses = []
        while True:
            try:
                msg = midi_q.get_nowait()
                if msg.type == 'note_on' and msg.velocity > 0:
                    active_notes.add(msg.note)
                    new_presses.append(msg.note)
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    active_notes.discard(msg.note)
            except queue.Empty:
                break

        if g_status == 'PLAYING':
            g_time += dt
            if g_idx >= len(groups):
                g_status = 'FINISHED'
            elif g_time >= groups[g_idx]['time']:
                g_time   = groups[g_idx]['time']
                g_status = 'WAITING'
                g_hit    = set()

        elif g_status == 'WAITING':
            required = {n['pitch'] for n in groups[g_idx]['notes']}
            for p in new_presses:
                if p in required:
                    g_hit.add(p)
            if g_hit >= required:
                g_score  += 1
                g_idx    += 1
                g_status  = 'PLAYING' if g_idx < len(groups) else 'FINISHED'

        wait_pitches = (
            [n['pitch'] for n in groups[g_idx]['notes']]
            if g_status == 'WAITING' and g_idx < len(groups) else []
        )

        if clients:
            payload = json.dumps({
                'type':         'state',
                'game_time':    g_time,
                'status':       g_status,
                'score':        g_score,
                'total':        len(groups),
                'active_notes': list(active_notes),
                'wait_pitches': wait_pitches,
                'hit_pitches':  list(g_hit),
            })
            dead = set()
            for ws in list(clients):
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.add(ws)
            clients.difference_update(dead)


def _midi_listener():
    try:
        ports = mido.get_input_names()
    except Exception as exc:
        print(f"MIDI input unavailable — keyboard input disabled: {exc}")
        return
    if not ports:
        print("No MIDI device found — keyboard input disabled.")
        return
    print(f"MIDI controller: {ports[0]}")
    with mido.open_input(ports[0]) as port:
        for msg in port:
            midi_q.put(msg)


@app.on_event("startup")
async def startup():
    asyncio.create_task(game_loop())
    if os.getenv("ENABLE_MIDI_INPUT", "").lower() in {"1", "true", "yes", "on"}:
        threading.Thread(target=_midi_listener, daemon=True).start()


if __name__ == '__main__':
    print("Open http://localhost:8000")
    uvicorn.run(app, host='0.0.0.0', port=8000)
