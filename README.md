# Piano Teacher

> Biến bất kỳ bài nhạc nào thành trò chơi piano tương tác — tìm kiếm bài hát, tải audio, chuyển đổi tự động sang MIDI, rồi luyện tập với nốt nhạc rơi và phản hồi từ AI coach.

---

## Demo

[![Watch the demo](https://img.shields.io/badge/▶%20Watch%20Demo-blue?style=for-the-badge)](https://github.com/ThuyMo/Piano_teacher)

---

## Problem

Người mới học đàn piano thường gặp hai rào cản lớn:

1. **Không có bản nhạc phù hợp.** Sheet nhạc truyền thống quá phức tạp với người mới, trong khi các app học piano chỉ có thư viện nhạc cố định — không thể học bài mình thích.
2. **Không có ai chỉnh sửa lỗi trong lúc luyện tập.** Người học tự luyện sẽ lặp đi lặp lại sai lầm mà không biết, không có ai gợi ý khi nào nên chậm lại hay chuyển sang tay nào.

Kết quả: người học bỏ cuộc sớm vì chán hoặc vì không có tiến bộ rõ rệt.

---

## Users

| Ai | Dùng như thế nào |
|----|-----------------|
| **Người mới học piano** | Tìm bài nhạc yêu thích từ YouTube/SoundCloud, luyện tập tay phải hoặc tay trái riêng với nốt nhạc rơi trực quan |
| **Giáo viên âm nhạc** | Tạo bài luyện tập cho học sinh từ bất kỳ bản audio nào, điều chỉnh tốc độ và chọn phần bài phù hợp trình độ |
| **Người học trung cấp** | Luyện cả hai tay đồng thời, nhận phản hồi AI về tempo và điểm yếu cụ thể |

---

## Solution

App xử lý toàn bộ pipeline từ audio thô đến trò chơi piano tương tác qua ba giai đoạn:

### 1. Tìm kiếm và tải nhạc

Người dùng tìm kiếm bài hát theo tên hoặc upload file audio trực tiếp. Hệ thống hỗ trợ hai nguồn:

- **YouTube** — tìm kiếm top 5 kết quả, preview 30 giây trước khi tải
- **SoundCloud** — thay thế không bị chặn trên datacenter IP; tự động fallback nếu YouTube thất bại

File audio (MP3/WAV/FLAC/M4A) được đưa qua pipeline xử lý tự động:

1. **Audio → MIDI** — `ffmpeg` chuẩn hoá audio, `transkun` (AI model) nhận diện nốt nhạc
2. **Tách tay** — thuật toán distance-based chia notes thành tay phải (`_RH.mid`) và tay trái (`_LH.mid`)
3. **Chuyển tông** — tự động detect key, transpose về C major / A minor cho người mới dễ chơi
4. **Đơn giản hoá** — chỉ giữ nốt cao nhất mỗi time group, phù hợp trình độ beginner

### 2. Chơi game — nốt nhạc rơi tương tác

Game hiển thị đàn piano 88 phím với nốt nhạc rơi từ trên xuống:

- **Xanh lam** — nốt đang rơi chưa cần nhấn
- **Vàng** — nốt cần nhấn ngay (game đang chờ)
- **Xanh lá** — nhấn đúng
- **Cam đỏ** — nhấn sai

Chế độ **Wait Mode**: game tạm dừng và chờ người chơi nhấn đúng nốt trước khi tiếp tục — không bỏ lỡ nốt nào. Hỗ trợ đổi tay (RH/LH/Cả hai) ngay trong lúc chơi mà không cần tải lại bài.

### 3. AI Coach — phản hồi thời gian thực

Sau mỗi section, **gemma-4-31b-it** phân tích kết quả chơi và đưa ra phản hồi:

- Gợi ý giảm tốc độ khi tỉ lệ lỗi cao
- Nhận xét các nốt hay bị sai nhất
- Khuyến khích khi người học tiến bộ

### Architecture

```
Browser (static/)
  │  ← dashboard tìm kiếm nhạc, game piano canvas, UI điều khiển
  │
  ├── HTTP (port 8080) ──→ FastAPI (app.py)
  │                            ├── GET  /                → dashboard.html
  │                            ├── POST /api/download    → tải YouTube/SoundCloud + pipeline
  │                            ├── GET  /api/search      → tìm YouTube (yt-dlp)
  │                            ├── GET  /api/search-soundcloud → tìm SoundCloud
  │                            ├── POST /load            → load bài vào game
  │                            ├── POST /set-hand        → đổi tay RH/LH/BOTH
  │                            ├── POST /set-tempo       → điều chỉnh tốc độ
  │                            └── GET  /status/{id}     → poll tiến trình xử lý
  │
  └── WebSocket /ws ──→ Game loop (30fps)
                            ├── Nhận MIDI input từ browser (Web MIDI API)
                            ├── Tính toán hit/miss/wait state
                            ├── Broadcast piano state cho canvas render
                            └── Gọi gemma-4-31b-it khi kết thúc section
```

**Audio processing pipeline:**

```
MP3/WAV/FLAC  →  ffmpeg  →  WAV  →  transkun  →  MIDI
     →  split_midi_hands  →  _RH.mid + _LH.mid
     →  chord_detector    →  transpose sang C/Am
     →  mid_to_pd         →  đơn giản hoá beginner
     →  _RH_processed.mid (file dùng trong game)
```

---

## How to Run

### Prerequisites

- Python 3.11+
- `ffmpeg` (cài qua `brew install ffmpeg` hoặc `apt-get install ffmpeg`)
- GreenNode MaaS API key (hoặc bất kỳ OpenAI-compatible endpoint nào)

### 1. Clone và cài đặt

```bash
git clone https://github.com/ThuyMo/Piano_teacher.git
cd Piano_teacher
pip install -r requirements.txt
```

### 2. Cấu hình môi trường

```bash
cp .env.example .env
```

Chỉnh sửa `.env`:

```env
# GreenNode MaaS (hoặc bất kỳ OpenAI-compatible LLM nào)
LLM_API_KEY=your-api-key-here
LLM_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1
LLM_MODEL=google/gemma-4-31b-it

# YouTube cookies (tuỳ chọn — cần nếu muốn tải từ YouTube trên cloud)
# YTDLP_COOKIES_B64=<base64 của Netscape cookie file chỉ chứa .youtube.com>
```

### 3. Khởi động server

```bash
uvicorn app:app --host 0.0.0.0 --port 8080 --reload
```

### 4. Mở UI

Truy cập `http://localhost:8080` trên trình duyệt.

**Quy trình sử dụng:**

1. Tìm kiếm bài hát trên **YouTube** hoặc **SoundCloud** (hoặc upload file audio trực tiếp)
2. Click **"Use this"** — hệ thống tải về và xử lý tự động (~30-60s)
3. Bài xuất hiện trong danh sách "Processed Files" → click **▶ Play**
4. Chọn tay (Tay phải / Tay trái / Cả hai), tốc độ, và phần bài muốn luyện
5. Luyện tập — game chờ bạn nhấn đúng nốt trước khi tiếp tục
6. Xem phản hồi AI sau mỗi section

### Optional: Docker

```bash
docker build --platform linux/amd64 -t piano-teacher .
docker run -p 8080:8080 --env-file .env piano-teacher
```

---

## Deploy to AgentBase

Chạy local là bước đầu. Để app hoạt động **production** với endpoint ổn định, không lo YouTube bị block, và AI coach luôn sẵn sàng — deploy lên **GreenNode AgentBase**.

### Dùng AgentBase Skills

[**greennode-agentbase-skills**](https://github.com/vngcloud/greennode-agentbase-skills) là bộ skill dành riêng cho Claude Code, hỗ trợ toàn bộ lifecycle: scaffold → config → deploy → monitor → teardown.

**Thêm skill vào project:**

```bash
echo "https://github.com/vngcloud/greennode-agentbase-skills" >> .claude/SKILLS.md
```

**Các lệnh chính:**

```
/agentbase-wizard init     # Scaffold cấu hình AgentBase cho project
/agentbase-identity        # Cấu hình tên, system prompt, personality của agent
/agentbase-deploy          # Build Docker image, push lên GreenNode Container Registry, tạo runtime
/agentbase-monitor         # Xem logs, CPU/Memory, distributed traces
```

---

### Lợi ích khi chạy trên AgentBase

#### Endpoint ổn định — URL không đổi khi update version

Mỗi agent có một **DEFAULT endpoint** với URL cố định. Deploy version mới — URL vẫn giữ nguyên, không cần cập nhật config ở phía người dùng.

---

#### Version control tự động — rollback bất kỳ lúc nào

Mỗi lần deploy tạo ra một **snapshot version** tự động. Xem lịch sử, so sánh, hoặc rollback về version cũ chỉ bằng vài click.

---

#### Monitoring tích hợp — CPU, Memory, Logs, Tracing

AgentBase tích hợp sẵn **vMonitor Platform**: CPU Usage, Memory Usage theo thời gian thực, truy vết từng request qua Distributed Tracing — không cần setup thêm công cụ observability.

---

#### SoundCloud không bị block trên datacenter

YouTube thường chặn datacenter IP. App tự động fallback sang SoundCloud (hoặc dùng `_ytdlp_download` với mobile clients) — người dùng không bao giờ thấy lỗi download.

---

## What to Customize

### Đổi model LLM

Trong `.env`, đặt `LLM_MODEL` thành bất kỳ model nào có trên GreenNode MaaS:

```env
LLM_MODEL=google/gemma-4-31b-it       # mặc định
# LLM_MODEL=qwen/qwen2.5-72b-instruct # đa ngôn ngữ tốt hơn
# LLM_MODEL=minimax/minimax-m1-40k    # context dài
```

### Đổi số nốt tìm kiếm YouTube/SoundCloud

Trong `app.py`, sửa `ytsearch5:` / `scsearch5:` thành số kết quả mong muốn:

```python
# app.py, hàm _yt_search và _sc_search
["yt-dlp", f"ytsearch10:{query} piano", ...]  # tăng lên 10 kết quả
```

### Tắt chế độ đơn giản hoá beginner

Trong `_run_pipeline` (app.py), bỏ dòng lọc nốt cao nhất để giữ nguyên tất cả nốt:

```python
# Thay dòng này:
processed_df = df.loc[df.groupby('grouped_time')['pitch'].idxmax()].reset_index(drop=True)
# Bằng:
processed_df = df  # giữ tất cả nốt, không đơn giản hoá
```

### Đổi màu nốt nhạc

Trong `static/index.html`, tìm phần render nốt rơi:

```javascript
if (isHit)       ctx.fillStyle = '#50f078';   // xanh lá = đúng
else if (isWait) ctx.fillStyle = '#ffc832';   // vàng = đang chờ
else             ctx.fillStyle = k.isBlack ? '#3270dc' : '#5096ff'; // xanh lam = rơi
```

### Đổi ngôn ngữ phản hồi AI

Trong `app.py`, tìm phần system prompt của LLM feedback và đổi ngôn ngữ:

```python
{"role": "system", "content": "You are a piano coach. Respond in English."}
```

---

## Project Structure

```
Piano_teacher/
├── app.py                    # FastAPI app — routes, game loop, pipeline
├── requirements.txt
├── Dockerfile
├── .env.example
│
├── model/                    # Audio & MIDI processing
│   ├── input_processor.py    # convert_audio_to_midi (ffmpeg + transkun)
│   ├── midi_processor.py     # split_midi_hands, extract_right_hand
│   ├── midi_to_array.py      # mid_to_pd — MIDI → DataFrame
│   ├── chord_detector.py     # detect key, transpose
│   └── transkun/             # AI transcription model
│
├── static/                   # Frontend
│   ├── dashboard.html        # Trang chính: tìm kiếm nhạc, danh sách bài
│   └── index.html            # Game piano: canvas render, WebSocket, MIDI input
│
├── artifact/                 # MIDI files đã xử lý (sinh ra lúc runtime)
│   ├── song_RH.mid           # Tay phải
│   ├── song_LH.mid           # Tay trái
│   ├── song_RH_transposed.mid
│   └── song_RH_processed.mid # File dùng trong game (đơn giản hoá beginner)
│
└── uploads/                  # Audio files tạm thời
```

---

## How GreenNode MaaS is Used

Tất cả AI calls đi qua **GreenNode MaaS** tại `https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1` qua OpenAI-compatible API:

```python
# app.py — AI feedback sau mỗi section
from openai import AsyncOpenAI

client = AsyncOpenAI(
    base_url=os.getenv("LLM_BASE_URL", "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"),
    api_key=os.getenv("LLM_API_KEY"),
)
response = await client.chat.completions.create(
    model=os.getenv("LLM_MODEL", "google/gemma-4-31b-it"),
    messages=[
        {"role": "system", "content": "Bạn là giáo viên piano..."},
        {"role": "user",   "content": f"Kết quả section: {stats}"},
    ],
    max_tokens=300,
    temperature=0.7,
)
```

**gemma-4-31b-it** xử lý một nhiệm vụ duy nhất: phân tích kết quả chơi của người dùng (điểm, nốt sai, tốc độ trung bình) và đưa ra lời khuyên ngắn gọn bằng tiếng Việt sau mỗi section luyện tập.
