# AI Watermark Studio (Phase 1 — Ảnh Tĩnh Cục Bộ)

Ứng dụng xóa watermark, logo và chữ trên ảnh tĩnh chạy **100% cục bộ (Offline / Privacy-first)** với **Microsoft Florence-2-base** (nhận diện tự động vùng watermark) và **Big-LaMa** (tái tạo nền tự nhiên), tối ưu cho laptop **16 GB RAM** và dòng **Intel Core Ultra (OpenVINO GPU/CPU)** cũng như NVIDIA CUDA / DirectML / CPU.

---

## Tính năng chính

- **Tô Mask 1:1 chuẩn độ phân giải gốc (`MaskCanvas`):** Brush, Eraser, Pan, Zoom quanh con trỏ, Undo/Redo, và trộn mask từ AI tự động dò mà không lệch pixel do DPI hay tỷ lệ màn hình.
- **Tự động phát hiện Watermark (Florence-2):** Hỗ trợ tùy chỉnh prompt (`watermark, logo, text, stamp, caption`) hoặc vẽ bổ sung thủ công.
- **Xóa Watermark & Bảo toàn ảnh gốc (Big-LaMa):**
  - Tự sửa hướng EXIF trước khi xử lý.
  - Tự đệm chia hết cho 8 (`pad_to_modulo=8`) và cắt đúng kích thước gốc.
  - Bảo toàn **100% pixel ngoài vùng mask** và giữ nguyên **kênh Alpha (trong suốt)** cho ảnh PNG RGBA.
  - Nở viền mask OpenCV (`dilation_px` `0..25`) triệt tiêu bóng mờ cạnh chữ.
- **Chế độ tiết kiệm RAM 16 GB:** `Singleton` + `Lazy-load` + hoán đổi tuần tự `Florence-2 ↔ LaMa` + tự động giải phóng RAM sau `180s` không dùng + nút `"Giải phóng RAM AI"` chủ động.
- **So sánh Trước/Sau & Desktop Launcher:** Thanh kéo `Before/After` mượt mà, xuất PNG lossless và chạy 1-click như phần mềm desktop độc lập (`--app`).

---

## Yêu cầu hệ thống

- **Hệ điều hành:** Windows 10/11 (khuyến nghị), Linux hoặc macOS.
- **RAM:** 16 GB (đã tối ưu chạy mượt với `LOW_MEM_MODE=true`; tối thiểu 8 GB khi chạy từng model).
- **Dung lượng đĩa trống:** ~2.5 GB cho môi trường `.venv` và trọng số `Big-LaMa` (~196 MB) + `Florence-2-base` (~550 MB–1 GB).
- **Phần mềm:** Python `3.11+` (hoặc `uv`) và Node.js `18+` (nếu build lại giao diện Frontend).

---

## Cài đặt & Khởi chạy nhanh trên Windows (1-Click)

### Bước 1 — Cài đặt & tải trọng số AI
Nhấp đúp hoặc chạy từ thư mục gốc dự án:

```bat
scripts\setup.bat
```

Script tự động:
1. Tạo `.venv` và cài toàn bộ thư viện từ `backend/requirements.txt`.
2. Build giao diện React vào `frontend/dist/`.
3. Tạo `.env` từ `.env.example` (nếu chưa có).
4. Tải & kiểm tra checksum `big-lama.pt` và `microsoft/Florence-2-base` vào `backend/models/`.

### Bước 2 — Mở ứng dụng
```bat
scripts\start_app.bat
```
Trình duyệt sẽ tự động mở cửa sổ desktop độc lập tại `http://127.0.0.1:8000` (Edge/Chrome `--app` mode). Đóng cửa sổ terminal để tắt server sạch sẽ.

---

## Chạy thủ công / Phát triển (Dev Mode)

### Backend (FastAPI)
```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Frontend (Vite Dev Server với Proxy `/api`)
```powershell
cd frontend
npm install
npm run dev
```

### Tải weights & kiểm tra riêng
```powershell
.\.venv\Scripts\python.exe scripts\download_models.py --dry-run
.\.venv\Scripts\python.exe scripts\download_models.py
```

---

## Chạy bằng Docker

```bash
docker compose up --build
```
Trước khi chạy, có thể tải sẵn trọng số vào `./backend/models` bằng `scripts/download_models.py` (thư mục này được mount trực tiếp qua volume).

---

## API Endpoints (`ApiPrefix = /api/v1`)

| Method | Endpoint | Mô tả |
|---|---|---|
| `GET` | `/api/v1/health` | Trạng thái server, danh sách model đang nạp trong RAM, uptime |
| `GET` | `/api/v1/hardware` | Quét CPU, OpenVINO GPU/CPU/NPU, PyTorch CUDA/CPU, DirectML, RAM |
| `POST` | `/api/v1/detect` | Tự động dò vùng watermark bằng Florence-2 → trả `mask_base64`, `bboxes` |
| `POST` | `/api/v1/inpaint` | Xóa vùng watermark theo mask bằng Big-LaMa → trả PNG + headers đo hiệu năng |
| `POST` | `/api/v1/models/unload` | Giải phóng ngay toàn bộ AI models khỏi RAM/VRAM |

---

## Kiểm thử (Tests)

```powershell
# Kiểm thử Backend (Unit + API FastAPI)
.\.venv\Scripts\python.exe -m pytest tests/ -v

# Kiểm thử Frontend (Canvas Coordinate Mapper)
cd frontend
npm test
```

---

## Cấu trúc dự án

```text
watermark_remove/
├── backend/
│   ├── app/
│   │   ├── api/routes.py               # REST API endpoints
│   │   ├── engines/                    # LaMa, Florence-2, MemoryManager
│   │   ├── media/                      # EXIF, Alpha PNG, Mask Dilation
│   │   ├── observability/              # Hardware Probe (CPU/GPU/NPU/RAM)
│   │   └── main.py                     # FastAPI entry & SPA static serving
│   └── models/manifest.json            # Metadata & checksum trọng số AI
├── contracts/api_contract.md           # Khóa chuẩn giao tiếp API & Canvas
├── frontend/src/
│   ├── canvas/                         # MaskCanvas 1:1, coordMapper, History
│   └── components/                     # Uploader, Controls, Slider, Hardware
├── scripts/                            # download_models.py, setup.bat, start_app.bat
└── tests/                              # pytest test suite
```
