"""
Piano Teacher – main web app.
Usage: python app.py  →  http://localhost:8000
"""
import asyncio
import base64
import json
import os
import queue
import re
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

import mido
import uvicorn
import yt_dlp
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

from model.input_processor import convert_audio_to_midi
from model.midi_processor import extract_right_hand
from model.helper import chord_detector, mid_to_pd, pd_to_str, str_to_mid, transpose

load_dotenv()

# ─── YouTube cookies (optional) ───────────────────────────────────────────────
# Set YTDLP_COOKIES_B64 = base64(cookies.txt) to bypass YouTube bot detection
# on cloud servers. If not set, yt-dlp runs without cookies (works on local).
_YTDLP_COOKIES_FILE: str | None = None
_ytdlp_cookies_b64 = os.getenv("YTDLP_COOKIES_B64", "").strip()
if _ytdlp_cookies_b64:
    try:
        raw = base64.b64decode(_ytdlp_cookies_b64)
        content = raw.decode("utf-8", errors="replace")
        # Rebuild valid Netscape cookie file. Keep #HttpOnly_ cookie records;
        # those are real Netscape cookie rows, not comments, and often carry
        # YouTube/Google auth state.
        lines = [
            l for l in content.splitlines()
            if l and (not l.startswith("#") or l.startswith("#HttpOnly_"))
        ]
        cookie_text = "# Netscape HTTP Cookie File\n" + "\n".join(lines) + "\n"
        _tmp = tempfile.NamedTemporaryFile(
            suffix=".txt", prefix="yt_cookies_", delete=False, mode="w"
        )
        _tmp.write(cookie_text)
        _tmp.close()
        _YTDLP_COOKIES_FILE = _tmp.name
        print(f"[yt-dlp] cookies loaded: {len(lines)} entries → {_YTDLP_COOKIES_FILE}")
    except Exception as _e:
        print(f"[yt-dlp] cookies error (will run without): {_e}")
        _YTDLP_COOKIES_FILE = None

BASE_DIR     = Path(__file__).parent
ARTIFACT_DIR = BASE_DIR / "artifact"
UPLOADS_DIR  = BASE_DIR / "uploads"
ARTIFACT_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)

app = FastAPI()
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# ─── LLM client (OpenAI-compatible) ──────────────────────────────────────────

_llm_api_key  = os.getenv("LLM_API_KEY", "")
_llm_base_url = os.getenv("LLM_BASE_URL", "")
_llm_model    = os.getenv("LLM_MODEL", "")

_llm: OpenAI | None = (
    OpenAI(api_key=_llm_api_key, base_url=_llm_base_url)
    if _llm_api_key and _llm_base_url else None
)

_NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def _pitch_name(pitch: int) -> str:
    return f"{_NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


def _suggest_finger(target_pitch: int, group_pitches: list, hand: str) -> int:
    """Return suggested finger (1–5) based on note position within the chord."""
    sorted_p = sorted(set(group_pitches))
    n = len(sorted_p)
    if n == 0:
        return 3
    try:
        idx = sorted_p.index(target_pitch)
    except ValueError:
        idx = min(range(n), key=lambda i: abs(sorted_p[i] - target_pitch))
    if n == 1:
        return 1 if hand == 'RH' else 5
    ratio = idx / (n - 1)
    # RH: thumb(1)=lowest pitch; LH: thumb(1)=highest pitch
    return 1 + round(ratio * 4) if hand == 'RH' else 5 - round(ratio * 4)


def _generate_ai_feedback(stats: dict) -> dict:
    """Call LLM to produce session feedback. Runs in a thread."""
    wrong_desc = ""
    if stats.get('wrong_notes'):
        details = []
        for wn in stats['wrong_notes'][-5:]:
            pressed       = _pitch_name(wn['pressed'])
            required_names = [_pitch_name(p) for p in wn['required']]
            details.append(f"chơi {pressed} nhưng cần {'+'.join(required_names)}")
        wrong_desc = "; ".join(details)

    lines = [
        f'Bài: "{stats["song"]}" | Tay: {stats["hand"]} | Tốc độ: {int(stats["tempo"]*100)}%',
        f'Chính xác: {stats["accuracy"]:.0%} ({stats["correct"]}/{stats["total"]}) | Sai: {stats["wrong_count"]} lần',
    ]
    if wrong_desc:
        lines.append(f'Lỗi: {wrong_desc}')
    lines.append(
        '\nTrả về JSON object duy nhất (tất cả giá trị là string hoặc array of string):\n'
        '{"feedback":"Câu nhận xét một đoạn ngắn khuyến khích học sinh.",'
        '"next_practice":"Gợi ý luyện tập cụ thể một câu.",'
        '"song_recommendations":["Tên bài 1","Tên bài 2","Tên bài 3"]}'
    )
    prompt = '\n'.join(lines)

    resp = _llm.chat.completions.create(
        model=_llm_model,
        messages=[
            {"role": "system", "content": "/no_thinking"},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=2048,
        temperature=0.3,
    )
    msg = resp.choices[0].message
    text = (msg.content or '').strip()
    print(f"[llm] raw response ({len(text)} chars): {text[:200]}")

    parsed: dict = {}
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        parsed = json.loads(match.group() if match else text)
    except Exception as e:
        print(f"[llm] JSON parse failed: {e}, text={text[:300]!r}")
        # Build fallback from raw text
        parsed = {
            "feedback": text or "Bài tập đã hoàn thành! Tiếp tục luyện tập để cải thiện.",
            "next_practice": "Thử lại bài với tốc độ chậm hơn để chú ý từng nốt nhạc.",
            "song_recommendations": ["Twinkle Twinkle Little Star", "Ode to Joy", "Happy Birthday"],
        }

    if isinstance(parsed.get('feedback'), list):
        parsed['feedback'] = ' '.join(parsed['feedback'])
    # Ensure all required keys exist
    parsed.setdefault("feedback", "Bài tập đã hoàn thành!")
    parsed.setdefault("next_practice", "Tiếp tục luyện tập đều đặn mỗi ngày.")
    parsed.setdefault("song_recommendations", [])
    return parsed


# ─── MIDI helpers ─────────────────────────────────────────────────────────────

def _file_exists(p: Path) -> bool:
    """Workaround: os.stat fails on macOS Docker virtiofs for Unicode filenames.
    listdir + open are unaffected."""
    try:
        return p.name in os.listdir(str(p.parent))
    except Exception:
        return False


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


# ─── Game state ───────────────────────────────────────────────────────────────

notes_data   = []
groups       = []
clients      = set()
midi_q       = queue.Queue()
active_notes = set()

g_time             = 0.0
g_status           = 'PLAYING'
g_idx              = 0
g_score            = 0
g_hit              = set()

# Teacher-agent extensions
g_tempo             = 1.0        # playback speed multiplier (0.5 / 0.75 / 1.0)
g_hand              = 'RH'       # 'RH' | 'LH' | 'BOTH'
g_current_song      = ''         # base stem (without _RH/_LH)
g_current_path      = ''         # full path of loaded MIDI
g_wrong_notes       = []         # [{group_idx, pressed, required, time}]
g_section_mistakes  = {}         # group_idx -> mistake count
g_section_hit_times = {}         # group_idx -> reaction time (seconds)
g_last_wrong        = None       # last wrong-note payload
g_last_wrong_at     = -999.0     # loop wall-clock time of last wrong note
g_wait_started_at   = 0.0        # loop wall-clock time when WAITING began

# Pre-computed feedback (kicked off the moment game reaches FINISHED)
g_feedback_cache: dict | None = None
g_feedback_future: asyncio.Future | None = None


def _reset_game(path: str) -> None:
    global notes_data, groups, g_time, g_status, g_idx, g_score, g_hit
    global g_wrong_notes, g_section_mistakes, g_section_hit_times
    global g_last_wrong, g_last_wrong_at, g_current_song, g_current_path
    global g_wait_started_at, g_feedback_cache, g_feedback_future

    g_current_path = path

    # Tag each note with its hand so the frontend can colour by hand.
    # For BOTH: merge _RH.mid + _LH.mid; for a single hand: tag from current file.
    base_dir = Path(path).parent
    stem_raw = Path(path).stem
    song_stem = stem_raw
    for suffix in ('_RH', '_LH'):
        if song_stem.endswith(suffix):
            song_stem = song_stem[:-len(suffix)]
            break

    if g_hand == 'BOTH':
        rh_p = base_dir / f"{song_stem}_RH.mid"
        lh_p = base_dir / f"{song_stem}_LH.mid"
        rh_notes = [dict(n, hand='RH') for n in _load_notes(str(rh_p))] if _file_exists(rh_p) else []
        lh_notes = [dict(n, hand='LH') for n in _load_notes(str(lh_p))] if _file_exists(lh_p) else []
        notes_data = sorted(rh_notes + lh_notes, key=lambda x: x['start'])
    else:
        tag = 'LH' if g_hand == 'LH' else 'RH'
        notes_data = [dict(n, hand=tag) for n in _load_notes(path)]

    groups         = _group_notes(notes_data)
    g_time         = (groups[0]['time'] - 4.0) if groups else 0.0
    g_status       = 'PLAYING'
    g_idx          = 0
    g_score        = 0
    g_hit          = set()
    g_wrong_notes       = []
    g_section_mistakes  = {}
    g_section_hit_times = {}
    g_last_wrong        = None
    g_last_wrong_at     = -999.0
    g_wait_started_at   = 0.0
    g_feedback_cache    = None
    g_feedback_future   = None

    g_current_song = song_stem


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


def _sc_search(query: str) -> list:
    result = subprocess.run(
        ["yt-dlp", f"scsearch5:{query}",
         "--dump-json", "--flat-playlist", "--quiet", "--no-warnings"],
        capture_output=True, text=True, timeout=30
    )
    entries = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        try:
            data = json.loads(line)
            url = data.get("url") or data.get("webpage_url", "")
            if not url:
                continue
            if not url.startswith("http"):
                url = "https://soundcloud.com" + url
            entries.append({
                "id": str(data.get("id", "")),
                "title": data.get("title", "Unknown"),
                "duration": data.get("duration"),
                "channel": data.get("uploader") or data.get("channel", ""),
                "url": url,
                "thumbnail": data.get("thumbnail", ""),
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

tasks: dict       = {}
_mp3_cache: dict  = {}


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "", value).strip(" ._-")
    stem = re.sub(r"\s+", " ", stem)
    return stem[:80] or "downloaded-song"


_YT_URL_RE = re.compile(
    r'(?:youtube\.com/(?:watch\?.*?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})'
)

def _extract_video_id(query: str) -> str | None:
    m = _YT_URL_RE.search(query)
    return m.group(1) if m else None


_YT_URL_RE = re.compile(
    r'(?:youtube\.com/(?:watch\?.*?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})'
)

def _extract_video_id(query: str) -> str | None:
    m = _YT_URL_RE.search(query)
    return m.group(1) if m else None


def _search_video_ids(song_name: str) -> list[str]:
    """Search YouTube with yt-dlp (flat extract, works from datacenter IPs)."""
    opts = {
        "quiet": True, "no_warnings": True,
        "extract_flat": True, "ignoreerrors": True,
        "extractor_args": {"youtube": {"player_client": ["mweb", "android"]}},
    }
    if _YTDLP_COOKIES_FILE:
        opts["cookiefile"] = _YTDLP_COOKIES_FILE
    with yt_dlp.YoutubeDL(opts) as ydl:
        res = ydl.extract_info(f"ytsearch8:{song_name}", download=False)
    entries = [e for e in (res or {}).get("entries", []) if e and e.get("id")]
    # Filter: no live, no long videos
    filtered = [
        e for e in entries
        if e.get("live_status") not in ("is_live", "is_upcoming")
        and (e.get("duration") or 0) <= 720
    ]
    return [e["id"] for e in (filtered or entries)[:6]]


def _soundcloud_download(song_name: str, output_path: Path, on_progress=None) -> str:
    """Download from SoundCloud — không bị block datacenter IP, không cần cookies."""
    def progress_hook(d):
        if d["status"] == "downloading" and on_progress:
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done  = d.get("downloaded_bytes", 0)
            on_progress(done, total)

    query = f"{song_name} piano"
    opts: dict = {
        "format":         "bestaudio/best",
        "outtmpl":        str(output_path.with_suffix(".%(ext)s")),
        "postprocessors": [{"key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3", "preferredquality": "128"}],
        "quiet":          True,
        "no_warnings":    True,
        "ignoreerrors":   True,
        "progress_hooks": [progress_hook],
        "noplaylist":     True,
    }
    # scsearch5: tìm 5 kết quả trên SoundCloud và tải cái đầu tiên match
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"scsearch5:{query}", download=True)

    # khi tìm playlist, info là dict với "entries"
    if info and info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        info = entries[0] if entries else None

    if info and output_path.with_suffix(".mp3").exists():
        title = info.get("title", song_name)
        print(f"[soundcloud] OK: {title}")
        return title

    raise RuntimeError(f"SoundCloud: không tìm thấy '{song_name}'")


def _ytdlp_download(song_name: str, output_path: Path, on_progress=None) -> str:
    """Fallback downloader using yt-dlp with tv_embedded client."""
    def progress_hook(d):
        if d["status"] == "downloading" and on_progress:
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done  = d.get("downloaded_bytes", 0)
            on_progress(done, total)

    video_ids = _search_video_ids(song_name)
    if not video_ids:
        raise FileNotFoundError(f"Không tìm thấy video cho '{song_name}'")

    last_err: Exception | None = None
    for vid_id in video_ids:
        url = f"https://www.youtube.com/watch?v={vid_id}"
        for leftover in output_path.parent.glob(output_path.name + ".*"):
            leftover.unlink(missing_ok=True)

        # Try no-cookie mobile clients first, then cookie-backed web client
        client_profiles: list[dict] = [
            {"clients": ["mweb", "android"], "cookies": False},
        ]
        if _YTDLP_COOKIES_FILE:
            client_profiles.append({"clients": ["web", "tv_embedded"], "cookies": True})

        for prof in client_profiles:
            opts: dict = {
                "format": "bestaudio/best",
                "outtmpl": str(output_path.with_suffix(".%(ext)s")),
                "postprocessors": [{"key": "FFmpegExtractAudio",
                                    "preferredcodec": "mp3", "preferredquality": "128"}],
                "quiet": True, "no_warnings": True, "ignoreerrors": False,
                "extractor_args": {"youtube": {"player_client": prof["clients"]}},
                "progress_hooks": [progress_hook],
            }
            if prof["cookies"] and _YTDLP_COOKIES_FILE:
                opts["cookiefile"] = _YTDLP_COOKIES_FILE
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                if info:
                    return info.get("title", song_name)
            except Exception as exc:
                last_err = exc
    raise RuntimeError(f"yt-dlp: không tải được '{song_name}'.\n[{last_err}]")


def _download_youtube_url(video_id: str, output_path: Path, on_progress=None) -> str:
    """Download a specific YouTube video by ID, trying pytubefix then yt-dlp."""
    import subprocess
    from pytubefix import YouTube

    url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        yt = YouTube(url, use_po_token=True)
        stream = (
            yt.streams.filter(only_audio=True).order_by("abr").desc().first()
            or yt.streams.filter(progressive=True).first()
        )
        if stream:
            ext = stream.subtype or "mp4"
            raw_name = f"{output_path.stem}_raw.{ext}"
            stream.download(output_path=str(output_path.parent), filename=raw_name)
            raw_path = output_path.parent / raw_name
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(raw_path),
                 "-vn", "-ar", "44100", "-ac", "2", "-b:a", "128k",
                 str(output_path.with_suffix(".mp3"))],
                capture_output=True, check=True,
            )
            raw_path.unlink(missing_ok=True)
            print(f"[pytubefix] OK: {yt.title}")
            return yt.title
    except Exception as pyt_err:
        print(f"[pytubefix] {video_id} failed: {pyt_err}")

    def progress_hook(d):
        if d["status"] == "downloading" and on_progress:
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done  = d.get("downloaded_bytes", 0)
            on_progress(done, total)

    profiles = [{"clients": ["mweb", "android"], "cookies": False}]
    if _YTDLP_COOKIES_FILE:
        profiles.append({"clients": ["web", "tv_embedded"], "cookies": True})

    last_err: Exception | None = None
    for prof in profiles:
        for leftover in output_path.parent.glob(output_path.name + ".*"):
            leftover.unlink(missing_ok=True)
        opts: dict = {
            "format": "bestaudio/best",
            "outtmpl": str(output_path.with_suffix(".%(ext)s")),
            "postprocessors": [{"key": "FFmpegExtractAudio",
                                "preferredcodec": "mp3", "preferredquality": "128"}],
            "quiet": True, "no_warnings": True, "ignoreerrors": False,
            "extractor_args": {"youtube": {"player_client": prof["clients"]}},
            "progress_hooks": [progress_hook],
        }
        if prof["cookies"] and _YTDLP_COOKIES_FILE:
            opts["cookiefile"] = _YTDLP_COOKIES_FILE
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            if info:
                return info.get("title", video_id)
        except Exception as exc:
            last_err = exc

    raise RuntimeError(
        f"Không thể tải video {video_id}. Thử upload file trực tiếp.\n[{last_err}]"
    )


def _youtube_title(video_id: str) -> str | None:
    """Get video title via YouTube oEmbed (public API, no auth needed)."""
    import urllib.request
    try:
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        with urllib.request.urlopen(url, timeout=8) as r:
            return json.loads(r.read()).get("title")
    except Exception:
        return None


def _clean_search_title(title: str) -> str:
    """Strip channel names / YouTube suffixes from video title for cleaner search."""
    # Remove trailing parts after ' | ' that look like channel/uploader names
    noise = re.compile(
        r'\s*\|\s*[^|]*(?:youtube|official|channel|music|records|vevo|topic)[^|]*$',
        re.IGNORECASE,
    )
    cleaned = noise.sub('', title).strip()
    # If still has ' | ', take first two parts joined with space
    parts = [p.strip() for p in cleaned.split('|') if p.strip()]
    return ' '.join(parts[:2]) if parts else title


def _download_song(song_name: str, output_path: Path, on_progress=None) -> str:
    """Nhận tên bài HOẶC YouTube URL. URL → thử download thẳng → fallback SoundCloud."""
    vid_id = _extract_video_id(song_name)
    if vid_id:
        # Thử download trực tiếp từ YouTube
        try:
            return _download_youtube_url(vid_id, output_path, on_progress)
        except Exception as yt_err:
            print(f"[download] YouTube direct failed ({yt_err}), trying SoundCloud with title...")
        # Fallback: lấy title qua oEmbed → clean → search SoundCloud
        raw_title = _youtube_title(vid_id) or song_name
        title = _clean_search_title(raw_title)
        print(f"[download] oEmbed title: {raw_title!r} → search: {title!r}")
        try:
            return _soundcloud_download(title, output_path, on_progress)
        except Exception as sc_err:
            raise RuntimeError(
                f"Không thể tải '{title}'. Thử upload file trực tiếp.\n[{sc_err}]"
            ) from sc_err

    sc_err: Exception | None = None
    try:
        return _soundcloud_download(song_name, output_path, on_progress)
    except Exception as e:
        sc_err = e
        print(f"[download] SoundCloud failed: {e}")
    try:
        return _ytdlp_download(song_name, output_path, on_progress)
    except Exception as ytd_err:
        raise RuntimeError(
            f"Không thể tải '{song_name}'. Thử tên khác hoặc upload file trực tiếp.\n"
            f"[SoundCloud: {sc_err}]\n[YouTube: {ytd_err}]"
        ) from ytd_err


async def _process_audio_task(task_id: str, input_path: Path) -> None:
    try:
        tasks[task_id]["step"] = "Đang nhận diện nốt nhạc (60s đầu)… ~20-40s"
        midi_path = await asyncio.to_thread(convert_audio_to_midi, str(input_path))

        tasks[task_id]["step"] = "Splitting hands..."
        rh_path = await asyncio.to_thread(extract_right_hand, str(midi_path))

        tasks[task_id]["step"] = "Analysing notes..."
        tonic, mode = await asyncio.to_thread(chord_detector, str(rh_path))
        df = await asyncio.to_thread(mid_to_pd, str(rh_path))

        tasks[task_id] = {
            "status": "done",
            "file":   rh_path.name,
            "key":    f"{tonic} {mode}",
            "notes":  int(len(df)),
            "median_duration": round(float(df['duration'].median()), 3),
        }
    except Exception as exc:
        tasks[task_id] = {"status": "error", "error": str(exc)}


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


@app.get("/learning_path")
async def learning_path_page():
    return FileResponse(BASE_DIR / "static" / "learning_path.html")


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
    hand: str = 'RH'


class SongRequest(BaseModel):
    query: str


class TempoRequest(BaseModel):
    tempo: float   # 0.5 | 0.75 | 1.0


class HandRequest(BaseModel):
    hand: str      # 'RH' | 'LH' | 'BOTH'

class DownloadRequest(BaseModel):
    url: str
    title: str = ""

class LoadPieceRequest(BaseModel):
    file: str
    piece_index: int
    total_pieces: int


@app.post("/load")
async def load_file(req: LoadRequest):
    global g_hand
    path = ARTIFACT_DIR / req.file
    if not _file_exists(path):
        return JSONResponse({"error": "File not found"}, status_code=404)
    g_hand = req.hand
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
        processed_df = df.loc[df.groupby('grouped_time')['pitch'].idxmax()].reset_index(drop=True)
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
@app.post("/set-tempo")
async def set_tempo(req: TempoRequest):
    global g_tempo
    g_tempo = max(0.25, min(1.0, req.tempo))
    return JSONResponse({"tempo": g_tempo})


@app.post("/set-hand")
async def set_hand_route(req: HandRequest):
    global g_hand
    if req.hand not in ('RH', 'LH', 'BOTH'):
        return JSONResponse({"error": "Invalid hand"}, status_code=400)
    if not g_current_song:
        return JSONResponse({"error": "No song loaded"}, status_code=400)

    g_hand = req.hand

    if req.hand == 'RH':
        candidates = [ARTIFACT_DIR / f"{g_current_song}_RH.mid",
                      ARTIFACT_DIR / f"{g_current_song}.mid"]
    elif req.hand == 'LH':
        candidates = [ARTIFACT_DIR / f"{g_current_song}_LH.mid",
                      ARTIFACT_DIR / f"{g_current_song}.mid"]
    else:
        candidates = [ARTIFACT_DIR / f"{g_current_song}_RH.mid",
                      ARTIFACT_DIR / f"{g_current_song}.mid"]

    for p in candidates:
        if _file_exists(p):
            _reset_game(str(p))
            return JSONResponse({"ok": True, "file": p.name})

    return JSONResponse({"error": "MIDI file not found for this hand"}, status_code=404)


@app.post("/restart")
async def restart_game():
    if not g_current_path:
        return JSONResponse({"error": "No song loaded"}, status_code=400)
    _reset_game(g_current_path)
    return JSONResponse({"ok": True})


def _build_stats() -> dict:
    total     = len(groups)
    correct   = g_score
    wrong_cnt = len(g_wrong_notes)
    accuracy  = correct / total if total else 0.0
    hard      = sorted(g_section_mistakes.items(), key=lambda x: x[1], reverse=True)[:3]
    hard_times = [round(groups[i]['time'], 2) for i, _ in hard if i < len(groups)]
    timings   = list(g_section_hit_times.values())
    avg_react = round(sum(timings) / len(timings), 3) if timings else 0.0
    return {
        'song':              g_current_song,
        'hand':              g_hand,
        'tempo':             g_tempo,
        'total':             total,
        'correct':           correct,
        'accuracy':          accuracy,
        'wrong_count':       wrong_cnt,
        'wrong_notes':       g_wrong_notes[-10:],
        'hard_section_times': hard_times,
        'avg_reaction_time': avg_react,
    }


def _start_feedback_precompute() -> None:
    """Kick off LLM feedback computation the moment game finishes (non-blocking)."""
    global g_feedback_cache, g_feedback_future
    if not _llm or g_feedback_future is not None:
        return
    stats = _build_stats()
    loop  = asyncio.get_event_loop()
    g_feedback_future = loop.run_in_executor(None, _generate_ai_feedback, stats)


@app.get("/session-feedback")
async def session_feedback():
    global g_feedback_cache, g_feedback_future

    if not groups:
        return JSONResponse({"error": "No song loaded"}, status_code=400)

    stats = _build_stats()

    ai = None
    if _llm:
        # Use pre-computed result if available, else compute now
        if g_feedback_cache is not None:
            ai = g_feedback_cache
        else:
            if g_feedback_future is None:
                _start_feedback_precompute()
            try:
                ai = await asyncio.wrap_future(g_feedback_future)
                g_feedback_cache = ai
            except Exception as exc:
                ai = {"error": str(exc)}

    return JSONResponse({**stats, 'ai_feedback': ai})


@app.post("/upload")
async def upload_audio(file: UploadFile = File(...)):
    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {"status": "processing", "step": "Uploading..."}
    content    = await file.read()
    input_path = UPLOADS_DIR / file.filename
    input_path.write_bytes(content)
    asyncio.create_task(_process_audio_task(task_id, input_path))
    return JSONResponse({"task_id": task_id})


@app.post("/download-song")
async def download_song(req: SongRequest):
    query = req.query.strip()
    if not query:
        return JSONResponse({"error": "Song name is required"}, status_code=400)

    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {"status": "processing", "step": "Searching YouTube…"}

    async def pipeline():
        try:
            vid_id = _extract_video_id(query)
            cache_key = vid_id if vid_id else query.lower().strip()
            if cache_key in _mp3_cache and _file_exists(_mp3_cache[cache_key]):
                input_path = _mp3_cache[cache_key]
                tasks[task_id]["step"] = f"Cached: {input_path.stem}"
            else:
                _mp3_cache.pop(cache_key, None)
                stem_path = UPLOADS_DIR / (vid_id if vid_id else _safe_stem(query))

                def on_progress(done, total):
                    if total:
                        tasks[task_id]["step"] = f"Downloading… {int(done*100/total)}%"
                    else:
                        tasks[task_id]["step"] = f"Downloading… {done/(1024*1024):.1f} MB"

                tasks[task_id]["step"] = "Downloading from YouTube…" if vid_id else "Searching & downloading…"
                await asyncio.to_thread(_download_song, query, stem_path, on_progress)
                input_path = stem_path.with_suffix(".mp3")
                _mp3_cache[cache_key] = input_path

            await _process_audio_task(task_id, input_path)
        except Exception as exc:
            tasks[task_id] = {"status": "error", "error": str(exc)}

    asyncio.create_task(pipeline())
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


@app.get("/api/search-soundcloud")
async def search_soundcloud_api(q: str):
    try:
        results = await asyncio.to_thread(_sc_search, q)
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


@app.post("/api/download-soundcloud")
async def download_soundcloud_api(req: DownloadRequest):
    task_id = str(uuid.uuid4())[:8]
    tasks[task_id] = {"status": "processing", "step": "Downloading from SoundCloud..."}

    async def pipeline():
        try:
            safe_title = re.sub(r'[^\w\s-]', '', req.title)[:40].strip() or task_id
            audio_path = UPLOADS_DIR / f"{safe_title}_{task_id}.mp3"
            tasks[task_id]["step"] = "Downloading audio from SoundCloud..."
            await asyncio.to_thread(_download_audio, req.url, str(audio_path))
        except Exception as exc:
            tasks[task_id] = {"status": "error", "error": str(exc)}
            return
        await _run_pipeline(audio_path, task_id)

    asyncio.create_task(pipeline())
    return JSONResponse({"task_id": task_id})


def _compute_pieces(midi_path: str) -> list:
    df = mid_to_pd(midi_path)
    if df.empty:
        return []
    times = sorted(df['grouped_time'].unique())
    n_groups = len(times)
    n_pieces = max(2, min(10, round(n_groups / 20)))
    chunk = max(1, n_groups // n_pieces)
    pieces = []
    for i in range(n_pieces):
        start_idx = i * chunk
        end_idx = (i + 1) * chunk if i < n_pieces - 1 else n_groups
        if start_idx >= n_groups:
            break
        slice_times = times[start_idx:end_idx]
        piece_df = df[df['grouped_time'].isin(set(slice_times))]
        pieces.append({
            "index": i,
            "label": f"Part {i + 1}",
            "note_groups": len(slice_times),
            "notes": int(len(piece_df)),
            "duration": round(float(slice_times[-1] - slice_times[0]), 1),
            "start_time": round(float(slice_times[0]), 1),
        })
    return pieces


def _extract_piece(midi_path: str, piece_index: int, total_pieces: int) -> Path:
    df = mid_to_pd(midi_path)
    times = sorted(df['grouped_time'].unique())
    n_groups = len(times)
    chunk = max(1, n_groups // total_pieces)
    start_idx = piece_index * chunk
    end_idx = (piece_index + 1) * chunk if piece_index < total_pieces - 1 else n_groups
    slice_times = set(times[start_idx:end_idx])
    piece_df = df[df['grouped_time'].isin(slice_times)].copy()
    offset = float(piece_df['grouped_time'].min())
    piece_df['grouped_time'] -= offset
    piece_df['timestamp'] -= offset
    piece_str = pd_to_str(piece_df)
    piece_path = ARTIFACT_DIR / f"{Path(midi_path).stem}_piece{piece_index}.mid"
    str_to_mid(piece_str, str(piece_path))
    return piece_path


@app.get("/api/pieces")
async def get_pieces(file: str):
    midi_path = ARTIFACT_DIR / file
    if not midi_path.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)
    try:
        pieces = await asyncio.to_thread(_compute_pieces, str(midi_path))
        return JSONResponse({"pieces": pieces, "total": len(pieces)})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/load_piece")
async def load_piece_route(req: LoadPieceRequest):
    midi_path = ARTIFACT_DIR / req.file
    if not midi_path.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)
    try:
        piece_path = _extract_piece(str(midi_path), req.piece_index, req.total_pieces)
        _reset_game(str(piece_path))
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


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
                note     = int(msg.get("note"))
                velocity = int(msg.get("velocity", 0))
                event    = msg.get("event")
                if event == "note_on" and velocity > 0:
                    midi_q.put(mido.Message("note_on", note=note, velocity=velocity))
                elif event in {"note_off", "note_on"}:
                    midi_q.put(mido.Message("note_off", note=note, velocity=0))
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(websocket)


# ─── Game loop ────────────────────────────────────────────────────────────────

async def game_loop():
    global g_time, g_status, g_idx, g_score, g_hit
    global g_last_wrong, g_last_wrong_at, g_wait_started_at

    last = asyncio.get_event_loop().time()

    while True:
        await asyncio.sleep(1 / 30)
        now  = asyncio.get_event_loop().time()
        dt   = now - last
        last = now

        # Drain MIDI queue
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

        # ── State machine ──────────────────────────────────────────────────────
        if g_status == 'PLAYING':
            g_time += dt * g_tempo          # tempo scaling
            if g_idx >= len(groups):
                g_status = 'FINISHED'
                _start_feedback_precompute()
            elif g_time >= groups[g_idx]['time']:
                g_time          = groups[g_idx]['time']
                g_status        = 'WAITING'
                g_hit           = set()
                g_wait_started_at = now

        elif g_status == 'WAITING':
            required = {n['pitch'] for n in groups[g_idx]['notes']}
            group_pitches = [n['pitch'] for n in groups[g_idx]['notes']]

            for p in new_presses:
                if p in required:
                    g_hit.add(p)
                else:
                    # ── Wrong note detected ────────────────────────────────────
                    g_section_mistakes[g_idx] = g_section_mistakes.get(g_idx, 0) + 1

                    # Suggest finger for the first still-needed correct note
                    still_needed = list(required - g_hit)
                    target = min(still_needed) if still_needed else (min(required) if required else p)
                    finger = _suggest_finger(target, group_pitches, g_hand)

                    g_last_wrong = {
                        'pressed':  p,
                        'required': list(required),
                        'finger':   finger,
                        'hand':     g_hand,
                    }
                    g_last_wrong_at = now
                    g_wrong_notes.append({
                        **g_last_wrong,
                        'group_idx': g_idx,
                        'time':      g_time,
                    })

            if g_hit >= required:
                # Track reaction time for this group
                g_section_hit_times[g_idx] = round(now - g_wait_started_at, 3)
                g_score  += 1
                g_idx    += 1
                if g_idx < len(groups):
                    g_status = 'PLAYING'
                else:
                    g_status = 'FINISHED'
                    _start_feedback_precompute()

        # ── Build payload ──────────────────────────────────────────────────────
        wait_pitches = (
            [n['pitch'] for n in groups[g_idx]['notes']]
            if g_status == 'WAITING' and g_idx < len(groups) else []
        )
        cur_mistakes = g_section_mistakes.get(g_idx, 0) if g_idx < len(groups) else 0

        show_wrong = (now - g_last_wrong_at) < 2.0

        payload = json.dumps({
            'type':             'state',
            'game_time':        g_time,
            'status':           g_status,
            'score':            g_score,
            'total':            len(groups),
            'active_notes':     list(active_notes),
            'wait_pitches':     wait_pitches,
            'hit_pitches':      list(g_hit),
            # Teacher extensions
            'wrong_note':       g_last_wrong if show_wrong else None,
            'section_mistakes': cur_mistakes,
            'suggest_slow':     cur_mistakes >= 3 and g_status == 'WAITING',
            'tempo':            g_tempo,
            'hand':             g_hand,
        })

        if clients:
            dead = set()
            for ws in list(clients):
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.add(ws)
            clients.difference_update(dead)


# ─── Physical MIDI listener ───────────────────────────────────────────────────

def _midi_listener():
    try:
        ports = mido.get_input_names()
    except Exception as exc:
        print(f"MIDI input unavailable: {exc}")
        return
    if not ports:
        print("No MIDI device found.")
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
