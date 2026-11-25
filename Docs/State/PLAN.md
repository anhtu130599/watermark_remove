# PLAN — AI WATERMARK STUDIO (PHASE 1: ẢNH TĨNH)
*Tài liệu điều phối của Role 01 (`CP§1`) kết hợp **Cơ chế Kiểm soát Token Thủ công** cho User. Mọi công đoạn chạy độc lập và **BẮT BUỘC DỪNG CHỜ USER DUYỆT** sau khi xong.*

---

## 1. Thông tin Dự án & Chốt Kiến trúc (`Decisions`)
- **Tên dự án:** AI Watermark Studio *(Phase 1: Xử lý Ảnh tĩnh — chưa bao gồm Video)*.
- **Spec gốc:** `Docs/system_spec_ai_watermark_remover_app.md`.
- **Kiến trúc chốt:** `Local Web App` (`Python FastAPI` + `React + Vite + TailwindCSS`). Khi build xong, FastAPI phục vụ trực tiếp `frontend/dist` trên `127.0.0.1:8000` kèm **1-Click Desktop Launcher** (`start_app.bat` mở cửa sổ độc lập `--app`). Kho mã nguồn sẵn sàng đẩy lên **GitHub** (`.gitignore` loại trừ weights/`.venv`/`node_modules` + script tự tải weights có kiểm tra SHA256).
- **Mục tiêu phần cứng chính:** ASUS Vivobook S 14 S3407CA — **Intel Core Ultra 7 255H, 16 GB RAM** (hỗ trợ đa backend: **Intel OpenVINO `AUTO/GPU/CPU`**, PyTorch CUDA/CPU, DirectML fallback; chế độ tiết kiệm RAM 16 GB với Singleton + Lazy-load + Auto-unload + Quantization `FP16`/`INT8`).

## 2. Cấu hình Nhân lực (`TeamProfile`, `ActiveRoles`, `ZoneReassignments`)
- **`TeamProfile`:** `lean-ai-media` (tối ưu nhân lực cho ứng dụng AI xử lý ảnh cục bộ).
- **`ActiveRoles`:** `[01, 02, 04, 05, 06, 07, 08]` *(tắt `03` và `09`)*.
- **`ZoneReassignments` (theo `CP§3`):**
  - `03` tắt → Ứng dụng chạy stateless cục bộ, không DB/Auth/Billing.
  - `09` tắt → `01` giữ `README.md` (phối hợp `08`), `04` giữ copy/nhãn UI, `07` giữ prompt preset mặc định cho Florence-2.

## 3. Quy trình Kiểm soát Token Thủ công (Manual Token Control Protocol)
1. **Nguyên tắc 1 Công đoạn = 1 Lượt duyệt:** Sau khi hoàn tất 1 công đoạn (`S0`–`S8`), Agent cập nhật trạng thái `[x] DONE` + ghi đúng **≤1 dòng tóm tắt** vào Bảng Tiến độ (Mục 5) rồi **DỪNG HẲN chờ User duyệt**; tuyệt đối không tự động chạy tiếp công đoạn sau.
2. **Vệ sinh ngữ cảnh (Context Hygiene):** Sau mỗi 1–2 công đoạn lớn (đặc biệt sau `S2`, `S3`, `S5`), User nên chạy `/compact` hoặc mở phiên chat mới và dán mẫu lệnh 3 dòng ở Mục 7.
3. **Kỷ luật `Read Whitelist`:** Ở mỗi công đoạn, Agent **chỉ được đọc các file trong `Read Whitelist`** của công đoạn đó; cấm quét toàn repo hay đọc lại file đã hoàn thiện ở bước trước nếu không sửa.
4. **Phân tầng Model đề xuất (User chọn thủ công trên UI chat):**
   - **Nhẹ / Nhanh:** `S0`, `S6`, `S7` *(scaffolding, UI components, scripts, README)*.
   - **Trung bình:** `S1`, `S4`, `S5` *(OpenCV/EXIF/Alpha, FastAPI routes, Canvas Brush/Zoom/Undo)*.
   - **Mạnh (High/Pro):** `S2`, `S3`, `S8` *(LaMa + Florence-2 + Intel OpenVINO + quản lý RAM 16 GB, QA E2E/debug sâu)*.

## 4. `ContractRegistry` (Đóng băng sớm để các công đoạn không hỏi lặp lại)
- **REST API Endpoints (`ApiPrefix = /api/v1`):**
  - `GET /api/v1/health` → `{ status, loaded_models[], low_mem_mode, uptime_s }`.
  - `GET /api/v1/hardware` → `{ cpu, devices[], recommended_backend, total_ram_mb, available_ram_mb }` *(devices gồm `CPU`, `OpenVINO GPU/CPU/NPU`, `CUDA`, `DirectML`)*.
  - `POST /api/v1/detect` → `multipart/form-data (image, prompt?, dilation_px?, backend?)` → `{ status, mask_base64, bboxes, latency_ms, backend_used }`.
  - `POST /api/v1/inpaint` → `multipart/form-data (image, mask, dilation_px?, backend?, low_mem_mode?)` → binary `image/png` kèm headers `X-Latency-Ms`, `X-Backend-Used`, `X-Ram-Used-MB`.
  - `POST /api/v1/models/unload` → `{ unloaded[], available_ram_mb }` *(giải phóng RAM/VRAM chủ động)*.
- **Core Interfaces:**
  - `IAiEngine` (`backend/app/engines/base.py`): `load()`, `unload()`, `is_loaded()`, `predict(...)`.
  - `IMediaProcessor` (`backend/app/media/`): `load_image_exif_rgb_alpha()`, `restore_alpha_png()`, `dilate_mask()`.
  - `CanvasContract` (`frontend/src/canvas/MaskCanvas.jsx`): props `{ imageUrl, aiMaskBase64, brushSize, tool, onMaskChange }` + ref method `exportMaskBlob()` xuất PNG mask nhị phân đúng kích thước `naturalWidth x naturalHeight`.

## 5. Bảng Tiến độ Tổng quan (`Phases` & Cổng dừng thủ công)
| Stage | Tên Công đoạn | Role | Staffing | Model gợi ý | Trạng thái | Tóm tắt kết quả (≤1 dòng) |
|---|---|---|---|---|---|---|
| `S0` | Chốt Context, Contracts & Scaffolding | 01 | Fast-Path (1 agent) | Nhẹ–TB | `[x] DONE` | Đã tạo `Project_Context.md`, `.gitignore`, `api_contract.md`, khung `backend/` & `frontend/` |
| `S1` | Backend Media Pipeline (EXIF, Alpha, Dilation) | 05 | Fast-Path (1 agent) | Trung bình | `[x] DONE` | Tạo `image_io.py`, `mask_ops.py`, `test_media.py` (`pytest` 7/7 PASS) |
| `S2` | AI Engine 1: LaMa Inpainting (OpenVINO + Pad mod 8) | 07 | Fast-Path (1 agent) | Mạnh | `[x] DONE` | Tạo `manifest.json`, `base.py`, `lama_inpainter.py`, `test_lama.py` (`pytest` 6/6 PASS) |
| `S3` | AI Engine 2: Florence-2 & Quản lý RAM 16 GB | 07 | Fast-Path (1 agent) | Mạnh | `[x] DONE` | Tạo `florence_detector.py`, `memory_manager.py`, `test_detector.py` (`pytest` 7/7 PASS) |
| `S4` | Backend FastAPI, Hardware Probe & Concurrency | 02+08 | Fast-Path (1 agent) | Trung bình | `[x] DONE` | Tạo `hardware_probe.py`, `api_models.py`, `routes.py`, `main.py`, `test_api.py` (`pytest` 8/8 PASS) |
| `S5` | Frontend Interactive Mask Canvas (Tọa độ 1:1) | 05 | Fast-Path (1 agent) | Trung bình | `[x] DONE` | Tạo `coordMapper.js`, `useCanvasHistory.js`, `MaskCanvas.jsx` (`vitest` 5/5 PASS) |
| `S6` | Frontend Studio UI, Slider & Hardware Panel | 04 | Fast-Path (1 agent) | Nhẹ–TB | `[x] DONE` | Tạo `apiClient.js`, 4 UI components & `App.jsx` (`vite build` 0 lỗi) |
| `S7` | Đóng gói 1-Click Local App & Chuẩn bị GitHub | 08+01 | Fast-Path (1 agent) | Nhẹ | `[x] DONE` | Tạo `download_models.py`, `setup.bat`, `start_app.bat`, Docker & `README.md` |
| `S8` | QA Gate Toàn diện (Static → Build → E2E → RAM) | 06 | Fast-Path (1 agent) | Mạnh | `[x] DONE` | Đạt 4/4 QA Gates (`pytest` 28/28, `vitest` 5/5, `openvino:GPU` ~4.5s warm, peak RSS 1,895 MB) |

## 6. Chi tiết 9 Công đoạn Thực thi (`S0` → `S8`)

### `S0` — Chốt Context, Contracts & Khung dự án (Scaffolding)
- **Mục tiêu:** Khởi tạo cấu hình dự án, khóa API Contract, `.gitignore` chuẩn GitHub và khung thư mục Backend/Frontend.
- **Read Whitelist:** `Docs/Roles/GEMINI.md`, `Docs/system_spec_ai_watermark_remover_app.md`, `Docs/State/PLAN.md`.
- **Output Files:** `Docs/Project_Context.md`, `.gitignore`, `contracts/api_contract.md`, `backend/app/config.py`, `.env.example`, `backend/requirements.txt`, khung `frontend/` (Vite + React + TailwindCSS).
- **Kiểm chứng & DoD:** Cấu trúc thư mục hợp lệ; `npm run build` ở `frontend/` (nếu đã có Node) và import `backend.app.config` không lỗi.
- **`[STOP — CHỜ USER DUYỆT]`:** Cập nhật bảng Mục 5, báo kết quả ngắn gọn và dừng chờ User cho phép chạy `S1`.

### `S1` — Backend Media Pipeline (EXIF, Alpha, Mask Dilation)
- **Mục tiêu:** Xử lý ảnh an toàn không lệch hướng EXIF, giữ kênh Alpha PNG, nở mask OpenCV `3–5px` triệt tiêu viền bóng mờ.
- **Read Whitelist:** `Docs/State/PLAN.md`, `contracts/api_contract.md`, `backend/app/config.py`.
- **Output Files:** `backend/app/media/image_io.py`, `backend/app/media/mask_ops.py`, `tests/test_media.py`.
- **Kiểm chứng & DoD:** `pytest tests/test_media.py` pass 100% (ảnh xoay EXIF 90°, PNG RGBA trong suốt, dilation 0px/3px/5px, ảnh kích thước lẻ).
- **`[STOP — CHỜ USER DUYỆT]`:** Cập nhật bảng Mục 5 và dừng chờ User cho phép chạy `S2`.

### `S2` — AI Engine 1: LaMa Inpainting (OpenVINO + PyTorch + Pad mod 8)
- **Mục tiêu:** Xây dựng `IAiEngine` và engine LaMa chạy đa backend (`OpenVINO GPU/AUTO/CPU` / `PyTorch CUDA/CPU` / fallback), tự pad chia hết cho 8 và crop đúng `(H, W)` gốc.
- **Read Whitelist:** `Docs/State/PLAN.md`, `contracts/api_contract.md`, `backend/app/config.py`, `backend/app/media/image_io.py`.
- **Output Files:** `backend/models/manifest.json`, `backend/app/engines/base.py`, `backend/app/engines/lama_inpainter.py`, `tests/test_lama.py`.
- **Kiểm chứng & DoD:** `pytest tests/test_lama.py` pass 100% (mock tensor + kiểm tra logic pad `mod 8` → crop đúng kích thước gốc, chuỗi fallback không crash khi thiếu GPU/weights).
- **`[STOP — CHỜ USER DUYỆT]`:** Cập nhật bảng Mục 5 và dừng chờ User (gợi ý `/compact` sau bước này).

### `S3` — AI Engine 2: Florence-2 Auto-Detect & Quản lý RAM 16 GB
- **Mục tiêu:** Tích hợp `microsoft/Florence-2-base` (task token `<OPEN_VOCABULARY_DETECTION>`, hỗ trợ OpenVINO/PyTorch, pin revision an toàn) + `MemoryManager` (Singleton, Lazy-load, Auto-unload khi `low_mem_mode=true`).
- **Read Whitelist:** `Docs/State/PLAN.md`, `backend/app/config.py`, `backend/app/engines/base.py`, `backend/models/manifest.json`.
- **Output Files:** `backend/app/engines/florence_detector.py`, `backend/app/engines/memory_manager.py`, `tests/test_detector.py`.
- **Kiểm chứng & DoD:** `pytest tests/test_detector.py` pass 100% (mock detect → bbox → binary mask, thread-safe lazy-load, auto-unload giải phóng tham chiếu).
- **`[STOP — CHỜ USER DUYỆT]`:** Cập nhật bảng Mục 5 và dừng chờ User (gợi ý `/compact` trước khi sang `S4`).

### `S4` — Backend FastAPI, Hardware Probe & Concurrency
- **Mục tiêu:** Hoàn thiện HTTP API, Hardware Probe (quét CPU/Intel Graphics-Arc/NPU/CUDA/RAM), validate upload (size, MIME/magic bytes), semaphore chống OOM/nghẽn async loop, và mount static `frontend/dist`.
- **Read Whitelist:** `Docs/State/PLAN.md`, `contracts/api_contract.md`, `backend/app/config.py`, chữ ký hàm từ `media/` & `engines/`.
- **Output Files:** `backend/app/observability/hardware_probe.py`, `backend/app/schemas/api_models.py`, `backend/app/api/routes.py`, `backend/app/main.py`, `tests/test_api.py`.
- **Kiểm chứng & DoD:** `pytest tests/test_api.py` pass 100% (`/health`, `/hardware`, `/detect`, `/inpaint`, `/models/unload`, reject file sai MIME/quá dung lượng).
- **`[STOP — CHỜ USER DUYỆT]`:** Cập nhật bảng Mục 5 và dừng chờ User cho phép chạy `S5`.

### `S5` — Frontend Interactive Mask Canvas (Tọa độ gốc 1:1 + Zoom/Pan/Undo)
- **Mục tiêu:** Xây dựng Canvas tương tác chính xác tuyệt đối ở độ phân giải ảnh gốc (`naturalWidth x naturalHeight`), hỗ trợ Brush, Eraser, Zoom/Pan, Undo/Redo, và trộn lớp mask từ AI Auto-Detect.
- **Read Whitelist:** `Docs/State/PLAN.md`, `contracts/api_contract.md`, `frontend/package.json`.
- **Output Files:** `frontend/src/canvas/coordMapper.js`, `frontend/src/canvas/useCanvasHistory.js`, `frontend/src/canvas/MaskCanvas.jsx`.
- **Kiểm chứng & DoD:** Unit test `coordMapper` (khi zoom/pan/DPI thay đổi) + `npm run build` 0 lỗi.
- **`[STOP — CHỜ USER DUYỆT]`:** Cập nhật bảng Mục 5 và dừng chờ User (gợi ý `/compact` sau bước này).

### `S6` — Frontend Studio UI, Before/After Slider & Hardware Panel
- **Mục tiêu:** Hoàn thiện giao diện 2 panel hiện đại (Upload, thanh công cụ Brush/Dilation/Auto-Detect/Remove, Before/After Slider, nút Download, Hardware & 16GB RAM Mode Panel).
- **Read Whitelist:** `Docs/State/PLAN.md`, `contracts/api_contract.md`, `frontend/src/canvas/MaskCanvas.jsx` (chỉ đọc props/API).
- **Output Files:** `frontend/src/services/apiClient.js`, `frontend/src/components/ImageUploader.jsx`, `frontend/src/components/ControlPanel.jsx`, `frontend/src/components/BeforeAfterSlider.jsx`, `frontend/src/components/HardwarePanel.jsx`, `frontend/src/App.jsx`.
- **Kiểm chứng & DoD:** `npm run build` 0 lỗi; kiểm tra responsive không lỗi layout và giải phóng `ObjectURL` đúng cách.
- **`[STOP — CHỜ USER DUYỆT]`:** Cập nhật bảng Mục 5 và dừng chờ User cho phép chạy `S7`.

### `S7` — Đóng gói 1-Click Local App & Chuẩn bị GitHub
- **Mục tiêu:** Tạo bộ script chạy 1 cú nhấp chuột trên Windows (`setup.bat`, `start_app.bat` mở cửa sổ `--app`), downloader weights kiểm tra SHA256 idempotent, Docker & `README.md` chuẩn GitHub.
- **Read Whitelist:** `Docs/State/PLAN.md`, `backend/models/manifest.json`, `backend/requirements.txt`, `backend/app/main.py` (chỉ kiểm tra port/static path).
- **Output Files:** `scripts/download_models.py`, `scripts/setup.bat`, `scripts/start_app.bat`, `Dockerfile`, `docker-compose.yml`, `README.md`.
- **Kiểm chứng & DoD:** Chạy dry-run/help check `download_models.py`, kiểm tra cú pháp `.bat`, rà soát `.gitignore` không lọt weights/`.env`/`.venv`/`node_modules`.
- **`[STOP — CHỜ USER DUYỆT]`:** Cập nhật bảng Mục 5 và dừng chờ User cho phép chạy `S8`.

### `S8` — QA Gate Toàn diện (Static → Build → E2E → Visual & RAM/Latency)
- **Mục tiêu:** Kiểm chứng toàn bộ hệ thống end-to-end với ảnh mẫu có watermark trên máy thực, chụp ảnh đa viewport (`ShotMatrix`), đo RAM peak ≤ 16 GB và Latency thực tế.
- **Read Whitelist:** `Docs/State/PLAN.md`, `Docs/Project_Context.md`, log kết quả từ `tests/`.
- **Output Files:** `Docs/QA_Reports/QA_Phase1.md`, ảnh chụp trong `Docs/Screenshots/`.
- **Kiểm chứng & DoD:** 4 cổng đạt 100% (`Static` + `Build` + `Functional/E2E` + `Visual/Resource`); tắt sạch server tạm; đặt `Verdict = PASS` và `DONE`.
- **`[STOP — CHỜ USER DUYỆT]`:** Báo cáo tổng kết cuối cùng kèm số liệu đo thực tế cho User.

## 7. Mẫu Prompt Điều phối Thủ công & `OpenQuestions`

### Mẫu Prompt gửi cho Agent ở đầu mỗi công đoạn (Copy-Paste)
```text
Hãy thực hiện ĐÚNG công đoạn <Sx> trong Docs/State/PLAN.md theo chuẩn Docs/Roles/GEMINI.md (Mục 1 Tiết kiệm Token).
Chỉ đọc các file trong Read Whitelist của <Sx>, tạo/sửa đúng Output Files và chạy lệnh kiểm chứng của <Sx>.
Xong việc: cập nhật dòng <Sx> trong Docs/State/PLAN.md, báo cáo ngắn gọn (≤5 dòng) và DỪNG HẲN chờ tôi duyệt công đoạn tiếp theo.
```

### `OpenQuestions` (Đã chốt trước `S0`)
1. **Môi trường máy hiện tại:** Đã cung cấp hướng dẫn cài **Node.js LTS** và **Python 3.11** (Windows `winget`/installer) ngay trong báo cáo `S0`.
2. **Chiến lược tải Model AI (`big-lama.pt` ~196 MB & `Florence-2-base` ~1 GB):** Chốt **tải trước cả 2 model** trong script cài đặt (`setup.bat` / `download_models.py` ở `S7`), còn khi chạy app vẫn bật **lazy-load + auto-unload** để bảo vệ 16 GB RAM.
