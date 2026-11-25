# QA REPORT — AI WATERMARK STUDIO (PHASE 1: ẢNH TĨNH)

- **Ngày kiểm chứng:** 2026-11-25
- **Môi trường phần cứng thực tế:** `Intel(R) Core(TM) Ultra 7 255H` · `Intel(R) Graphics (iGPU)` (`openvino:GPU`) · `Intel(R) AI Boost` (`openvino:NPU`) · RAM hệ thống `15,807 MB` (~16 GB) · Windows 11
- **Verdict tổng thể:** **PASS** *(4/4 QA Gates đạt yêu cầu; toàn bộ server tạm đã tắt sạch sau kiểm chứng)*

---

## 1. Static Gate
- **Python syntax & bytecode (`compileall`):** `.\.venv\Scripts\python.exe -m compileall -q backend scripts tests` → **Exit 0** (0 lỗi cú pháp).
- **Trọng số AI cục bộ & Checksum (`download_models.py --check`):**
  - `backend/models/big-lama.pt`: **Hợp lệ** (`196.3 MB`, khớp SHA256 `7ba7aa7ac37a...`).
  - `backend/models/florence2-base/`: **Hợp lệ** (đủ `config.json`, `preprocessor_config.json`, `model.safetensors`).
- **Bảo mật & Đóng gói GitHub (`.gitignore`):** Đã loại trừ `.venv/`, `.python/`, `frontend/node_modules/`, `frontend/dist/`, `.env`, `backend/models/*` (chỉ giữ `!backend/models/manifest.json` và `!backend/models/.gitkeep`).

---

## 2. Build Gate
- **Frontend Unit Tests (`vitest run`):** **5/5 PASSED** (`940ms`) — `frontend/src/canvas/__tests__/coordMapper.test.js` (test `computeFitTransform`, roundtrip `1:1` across zooms/pans/CSS offsets, out-of-bounds clamping, zoom-around-pointer invariance, brush diameter scaling).
- **Frontend Production Bundle (`vite build`):** **Exit 0** (`2.10s`):
  - `frontend/dist/index.html` (`0.49 kB`)
  - `frontend/dist/assets/index-BGLYOyw6.css` (`20.99 kB`)
  - `frontend/dist/assets/index-B98OqR86.js` (`195.18 kB`)
- **Backend Full Test Suite (`pytest tests/ -v`):** **28/28 PASSED** (`3.49s`):
  - `tests/test_api.py`: `8/8` PASSED (bao gồm `test_static_frontend_dist_spa_serving` phục vụ trực tiếp `frontend/dist`).
  - `tests/test_detector.py`: `7/7` PASSED.
  - `tests/test_lama.py`: `6/6` PASSED.
  - `tests/test_media.py`: `7/7` PASSED.

---

## 3. Functional & Real-Model E2E Gate (`http://127.0.0.1:8000`)

Kiểm thử trực tiếp trên tiến trình `uvicorn backend.app.main:app` kết nối weights thật (`Florence-2-base` + `Big-LaMa` với `LOW_MEM_MODE=true`):

| Bước kiểm thử | Endpoint | Kích thước / Mode | Backend thực chạy | Latency (ms) | RAM RSS App (MB) | Kết quả |
|---|---|---|---|---:|---:|---|
| Dò phần cứng | `GET /api/v1/hardware` | — | Probe Windows + OpenVINO + ORT | — | — | Phát hiện đủ `openvino:GPU`, `openvino:CPU`, `openvino:NPU`, `onnx:dml`, `pytorch:cpu` |
| Auto-Detect (Cold) | `POST /api/v1/detect` | `1280×720` PNG | `pytorch:cpu` | `34,111.02` | — | Trả response hợp lệ `200 OK` (nạp `florence2` thành công không lỗi `flash_attn`) |
| Inpaint RGB (Cold convert + Sequential Swap) | `POST /api/v1/inpaint` | `1280×720` RGB | `openvino:GPU` (Intel iGPU FP16) | `32,675.89` | `1,895` | Tự convert TorchScript → OpenVINO FP16 dynamic IR, đẩy `florence2` khỏi RAM (`loaded_models == ["lama"]`) |
| Inpaint RGBA (Warm iGPU) | `POST /api/v1/inpaint` | `512×512` RGBA | `openvino:GPU` | **`4,505.80`** | `1,888` | Giữ nguyên `RGBA` + `corner_alpha == 0`; tốc độ warm **< 5,000 ms** |
| Giải phóng RAM | `POST /api/v1/models/unload` | — | — | — | — | Xả `["lama"]` sạch sẽ, `GET /api/v1/health` → `loaded_models: []` |

> **Ghi chú kỹ thuật thực tế:**
> - Lần chạy đầu của `LaMa` chuyển đổi `big-lama.pt` sang OpenVINO FP16 IR có kiểm chứng shape động (`(64,64)` và `(64,80)`) và lưu cache tại `backend/models/openvino/big-lama.xml` (gitignored); từ lần thứ hai trở đi trên `openvino:GPU`, thời gian inpaint chỉ còn `~4.5s`.
> - RSS tiến trình Python cao nhất đo được là **`1,895 MB`** (~1.85 GB), an toàn tuyệt đối trong ngưỡng **16 GB RAM** (`15,807 MB`).

---

## 4. Visual & Responsive Gate (`Docs/Screenshots/`)

Ảnh chụp kiểm tra giao diện thực tế từ `http://127.0.0.1:8000` (dùng Chrome `--headless=new` sau khi tắt server sạch):

- `Docs/Screenshots/desktop_1440x900.png` (`86,565 bytes`) — Bố cục 2 panel (vùng `ImageUploader` / `MaskCanvas` bên trái, `ControlPanel` + `HardwarePanel` bên phải) hiển thị sắc nét trên nền tối, thông số `Intel(R) Core(TM) Ultra 7 255H`, `Đề xuất: openvino:GPU`, badge `NPU Ready` hiển thị chính xác.
- `Docs/Screenshots/desktop_1280x720.png` (`69,826 bytes`) — Hiển thị gọn gàng trên màn hình laptop 720p, thanh cuộn sidebar hoạt động độc lập.
- `Docs/Screenshots/mobile_390x844.png` (`38,937 bytes`) — Bố cục xếp dọc 1 cột trên thiết bị di động (`App.jsx` & `ControlPanel.jsx` đã bổ sung `min-w-0`, `overflow-x-hidden` và thu gọn padding nút lưới 3 cột). *(Lưu ý môi trường chụp: `chrome_devtools` MCP chưa kết nối nên dùng Chrome desktop `--headless=new --window-size=390,844`; Chrome trên Windows áp giới hạn chiều rộng cửa sổ tối thiểu ~500px trước khi crop ảnh PNG về 390px).*

---

## 5. Danh sách Artifact hoàn thiện (`S5`–`S8`)
- **Canvas & UI (`S5`, `S6`):** `frontend/src/canvas/{coordMapper.js,useCanvasHistory.js,MaskCanvas.jsx}`, `frontend/src/services/apiClient.js`, `frontend/src/components/{ImageUploader,ControlPanel,BeforeAfterSlider,HardwarePanel}.jsx`, `frontend/src/App.jsx`.
- **Packaging (`S7`):** `scripts/{download_models.py,setup.bat,start_app.bat}`, `Dockerfile`, `docker-compose.yml`, `README.md`.
- **QA (`S8`):** `Docs/QA_Reports/QA_Phase1.md`, `Docs/Screenshots/{desktop_1440x900,desktop_1280x720,mobile_390x844}.png`.

---

## 6. Post-Release Hotfix (2026-11-25)
- **Vấn đề phát hiện trên ảnh thực (`918×1024`):** Khi chạy `Big-LaMa` với `openvino:GPU` ở chế độ `FP16`, lớp biến đổi Fourier `2D FFT` vượt giới hạn số thực `FP16` (`65,504`) sinh ra toàn bộ `NaN` và bị `np.clip(...).astype(np.uint8)` biến thành vùng đen `#000000`.
- **Khắc phục đã áp dụng:**
  - Ép độ chính xác `FP32` (`INFERENCE_PRECISION_HINT="f32"`, `compress_to_fp16=False`, cache mới `backend/models/openvino/big-lama-fp32.xml`) trong `backend/app/engines/lama_inpainter.py`.
  - Chặn `NaN`/`Inf` ngay trong `postprocess_lama_output()` kèm fallback tự động sang `pytorch:cpu`.
  - Ở chế độ `auto`, ưu tiên `openvino:CPU` (AVX2/OneDNN `~3.3s` warm trên `918×1024`) trước `openvino:GPU` (`~15.8s` FP32).
- **Kiểm chứng sau sửa:** `pytest tests/ -v` đạt **30/30 PASSED** (`4.91s`), và kiểm tra trực tiếp trên ảnh mẫu thực tế cho kết quả xóa sạch dấu `✦` ở góc phải dưới mà không còn hiện tượng tô đen ở cả `openvino:CPU` lẫn `openvino:GPU`.
