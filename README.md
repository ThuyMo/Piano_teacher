# Piano Teacher

> Biến bất kỳ bài nhạc nào thành trò chơi piano tương tác — tìm kiếm bài hát, tải audio, chuyển đổi tự động sang MIDI, rồi luyện tập với nốt nhạc rơi và phản hồi từ AI coach.

---

## Demo

[![Watch the demo](https://vngms-my.sharepoint.com/:v:/g/personal/montt_vng_com_vn/IQBzDV-HnRM5Rbg028CyZAvdAc-TAUBIJl-UXfvnDaGxsG4?nav=eyJyZWZlcnJhbEluZm8iOnsicmVmZXJyYWxBcHAiOiJPbmVEcml2ZUZvckJ1c2luZXNzIiwicmVmZXJyYWxBcHBQbGF0Zm9ybSI6IldlYiIsInJlZmVycmFsTW9kZSI6InZpZXciLCJyZWZlcnJhbFZpZXciOiJNeUZpbGVzTGlua0NvcHkifX0&e=bQmNbo)

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
| **Người học trung cấp** | Luyện cả hai tay đồng thời, dùng chế độ kiểm tra để AI đánh giá khả năng thực tế |

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
4. **Đơn giản hoá** — RH giữ nốt cao nhất, LH giữ nốt thấp nhất mỗi time group, phù hợp trình độ beginner

### 2. Learning Path — luyện tập có lộ trình

Trang **Learning Path** chia bài nhạc thành các phần nhỏ (piece) để luyện từng đoạn:

- Chọn từng piece (đoạn 1, đoạn 2, …) theo trình độ
- **Chế độ luyện tập (Practice)**: game chờ nhấn đúng nốt, có gợi ý ngón tay, có cảnh báo khi sai liên tục
- **Chế độ kiểm tra (Test)**: chơi tự do không có gợi ý — AI chấm điểm và đưa ra nhận xét chi tiết từng nốt

### 3. Chơi game — nốt nhạc rơi tương tác

Game hiển thị đàn piano 88 phím với nốt nhạc rơi từ trên xuống:

- **Xanh lam** — nốt đang rơi chưa cần nhấn
- **Vàng** — nốt cần nhấn ngay (game đang chờ)
- **Xanh lá** — nhấn đúng
- **Cam đỏ** — nhấn sai

Chế độ **Wait Mode**: game tạm dừng và chờ người chơi nhấn đúng nốt trước khi tiếp tục. Hỗ trợ đổi tay (RH/LH/Cả hai) ngay trong lúc chơi — LH và BOTH đều dùng file đã transpose và simplify tương ứng.

### 4. AI Coach — phản hồi thời gian thực

Sau mỗi section, **gemma-4-31b-it** phân tích kết quả chơi và đưa ra phản hồi:

- Gợi ý giảm tốc độ khi tỉ lệ lỗi cao
- Nhận xét các nốt hay bị sai nhất
- Khuyến khích khi người học tiến bộ

Ở chế độ kiểm tra, AI phân tích từng nốt bấm sai/đúng theo timeline và đưa ra đánh giá toàn diện hơn.

### Architecture

```
Browser (static/)
  │  ← dashboard tìm kiếm nhạc, learning path, game piano canvas
  │
  ├── HTTP (port 8080) ──→ FastAPI (app.py)
  │                            ├── GET  /                      → dashboard.html
  │                            ├── GET  /learning_path         → learning_path.html
  │                            ├── GET  /game                  → index.html (game)
  │                            ├── POST /api/download          → tải YouTube/SoundCloud + pipeline
  │                            ├── GET  /api/search            → tìm YouTube (yt-dlp)
  │                            ├── GET  /api/search-soundcloud → tìm SoundCloud
  │                            ├── GET  /api/pieces            → danh sách pieces của bài
  │                            ├── POST /api/load_piece        → load một piece vào game
  │                            ├── POST /set-hand              → đổi tay RH/LH/BOTH
  │                            ├── POST /set-tempo             → điều chỉnh tốc độ
  │                            ├── POST /set-test-mode         → bật/tắt chế độ kiểm tra
  │                            ├── GET  /test-result           → kết quả chế độ kiểm tra
  │                            └── GET  /status/{id}           → poll tiến trình xử lý
  │
  └── WebSocket /ws ──→ Game loop (30fps, per-session)
                            ├── Nhận MIDI input từ browser (Web MIDI API)
                            ├── Tính toán hit/miss/wait state
                            ├── Broadcast piano state cho canvas render
                            └── Gọi gemma-4-31b-it khi kết thúc section
```

**Audio processing pipeline:**

```
MP3/WAV/FLAC  →  ffmpeg  →  WAV  →  transkun  →  MIDI
     →  split_midi_hands  →  _RH.mid + _LH.mid
     →  chord_detector    →  transpose sang C/Am (cả RH lẫn LH)
     →  mid_to_pd         →  đơn giản hoá beginner
     →  _RH_processed.mid + _LH_processed.mid (dùng trong game)
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
3. Bài xuất hiện trong danh sách → click **▶ Play** để vào Learning Path
4. Chọn đoạn bài (piece), chọn tay (Tay phải / Tay trái / Cả hai) và tốc độ
5. **Luyện tập**: game chờ bạn nhấn đúng nốt trước khi tiếp tục
6. **Kiểm tra**: chơi tự do, AI chấm điểm và nhận xét sau khi hoàn thành

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

Trong `_run_pipeline` (app.py), bỏ dòng lọc nốt để giữ nguyên tất cả nốt:

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
│   ├── learning_path.html    # Learning path: chọn piece, luyện tập / kiểm tra
│   └── index.html            # Game piano: canvas render, WebSocket, MIDI input
│
├── artifact/                 # MIDI files đã xử lý (sinh ra lúc runtime)
│   ├── song_RH.mid           # Tay phải (raw)
│   ├── song_LH.mid           # Tay trái (raw)
│   ├── song_RH_processed.mid # Tay phải đã transpose + simplify
│   ├── song_LH_processed.mid # Tay trái đã transpose + simplify
│   └── song_RH_processed_piece0.mid  # Piece được cắt ra để luyện
│
└── uploads/                  # Audio files tạm thời
```

---

## How GreenNode MaaS is Used

Tất cả AI calls đi qua **GreenNode MaaS** tại `https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1` qua OpenAI-compatible API:

```python
# app.py — AI feedback sau mỗi section
from openai import OpenAI

client = OpenAI(
    base_url=os.getenv("LLM_BASE_URL", "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"),
    api_key=os.getenv("LLM_API_KEY"),
)
response = client.chat.completions.create(
    model=os.getenv("LLM_MODEL", "google/gemma-4-31b-it"),
    messages=[
        {"role": "system", "content": "/no_thinking"},
        {"role": "user",   "content": f"Kết quả section: {stats}"},
    ],
    max_tokens=400,
    temperature=0.3,
    timeout=15,
)
```

**gemma-4-31b-it** xử lý hai nhiệm vụ:
1. **Practice feedback** — phân tích kết quả chơi (điểm, nốt sai, tốc độ) và đưa ra lời khuyên ngắn gọn sau mỗi section
2. **Test feedback** — đánh giá chi tiết từng nốt bấm theo timeline, chấm điểm tổng thể và gợi ý bài luyện tiếp theo
