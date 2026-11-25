# API & MODULE CONTRACTS — AI WATERMARK STUDIO (PHASE 1)
*Đóng băng cho `S1`–`S8`. Mọi thay đổi sau `S0` chỉ được phép mở rộng (additive).*

## 1. REST API (`ApiPrefix = /api/v1`)

### `GET /api/v1/health`
- **Response `200 OK`:**
  ```json
  {
    "status": "ok",
    "loaded_models": ["lama"],
    "low_mem_mode": true,
    "uptime_s": 12.4
  }
  ```

### `GET /api/v1/hardware`
- **Response `200 OK`:**
  ```json
  {
    "cpu": "Intel(R) Core(TM) Ultra 7 255H",
    "devices": [
      { "id": "openvino:GPU", "name": "Intel Graphics / Arc (OpenVINO)", "type": "igpu", "available": true },
      { "id": "openvino:CPU", "name": "Intel CPU (OpenVINO)", "type": "cpu", "available": true },
      { "id": "pytorch:cpu", "name": "PyTorch CPU", "type": "cpu", "available": true }
    ],
    "recommended_backend": "openvino:AUTO",
    "total_ram_mb": 16384,
    "available_ram_mb": 7200
  }
  ```

### `POST /api/v1/detect`
- **Request:** `multipart/form-data`
  - `image`: File ảnh bắt buộc (`image/jpeg`, `image/png`, `image/webp`; `<= 20 MB`, `<= 4096 px`).
  - `prompt`: `string` tùy chọn (mặc định `"watermark, logo, text, stamp, caption"`).
  - `dilation_px`: `int` `0..25` tùy chọn (mặc định `5`).
  - `backend`: `string` tùy chọn (mặc định `"auto"`).
- **Response `200 OK`:**
  ```json
  {
    "status": "success",
    "mask_base64": "data:image/png;base64,...",
    "bboxes": [[12, 45, 120, 80]],
    "width": 1920,
    "height": 1080,
    "latency_ms": 842.5,
    "backend_used": "openvino:GPU"
  }
  ```

### `POST /api/v1/inpaint`
- **Request:** `multipart/form-data`
  - `image`: File ảnh gốc bắt buộc.
  - `mask`: File ảnh mask Grayscale/RGBA bắt buộc (khớp tỷ lệ/kích thước gốc).
  - `dilation_px`: `int` `0..25` tùy chọn (mặc định `5`).
  - `backend`: `string` tùy chọn (mặc định `"auto"`).
  - `low_mem_mode`: `bool` tùy chọn (mặc định `true`).
- **Response `200 OK`:** Binary `image/png` (đã xóa watermark, giữ kênh Alpha nếu ảnh gốc có Alpha).
  - **Response Headers (phải mở trong CORS `expose_headers`):**
    - `X-Latency-Ms`: thời gian suy luận + xử lý (ms).
    - `X-Backend-Used`: backend thực tế đã chạy (vd `openvino:GPU`, `pytorch:cpu`).
    - `X-Ram-Used-MB`: RAM RSS của tiến trình sau khi chạy.

### `POST /api/v1/models/unload`
- **Response `200 OK`:**
  ```json
  {
    "status": "ok",
    "unloaded": ["florence2", "lama"],
    "available_ram_mb": 9450
  }
  ```

### Chuẩn Lỗi JSON
`{ "detail": "<mô tả lỗi rõ ràng>", "code": "<ERROR_CODE>" }`
- `400 BAD_REQUEST` · `413 PAYLOAD_TOO_LARGE` · `415 UNSUPPORTED_MEDIA_TYPE` · `422 VALIDATION_ERROR` · `429 TOO_MANY_REQUESTS` · `500 INTERNAL_ERROR` · `503 MODEL_UNAVAILABLE`.

---

## 2. Internal Python Contracts

### `IMediaProcessor` (`backend/app/media/`)
- `validate_and_load_image(data: bytes, max_size_mb: int, max_res_px: int) -> tuple[np.ndarray, np.ndarray | None, tuple[int, int]]`
  *(Kiểm tra magic bytes JPEG/PNG/WebP, giới hạn kích thước, áp dụng `exif_transpose`, tách trả `(rgb_uint8, alpha_uint8 | None, (orig_w, orig_h))`)*.
- `bboxes_to_mask(bboxes: list[list[int]], width: int, height: int) -> np.ndarray` *(trả `uint8` shape `(H, W)` giá trị `0`/`255`)*.
- `dilate_mask(mask_uint8: np.ndarray, kernel_px: int) -> np.ndarray` *(mở rộng vùng mask `0..25px`)*.
- `encode_png_with_alpha(rgb_uint8: np.ndarray, alpha_uint8: np.ndarray | None) -> bytes`.

### `IAiEngine` (`backend/app/engines/base.py`)
- Thuộc tính: `name: str`, `is_loaded: bool`, `backend_used: str`.
- Phương thức: `load(backend: str = "auto") -> None`, `unload() -> None`.

---

## 3. Frontend Canvas Contract (`frontend/src/canvas/MaskCanvas.jsx`)
- **Props:** `{ imageUrl, aiMaskBase64, tool, brushSize, maskOpacity, onHistoryChange }` (`tool` ∈ `'brush' | 'eraser' | 'pan'`).
- **Imperative `ref` methods:**
  - `exportMaskBlob(): Promise<Blob | null>` — xuất PNG mask nhị phân đúng kích thước gốc `(naturalWidth x naturalHeight)`.
  - `clearMask(): void`, `undo(): void`, `redo(): void`, `hasMask(): boolean`.
