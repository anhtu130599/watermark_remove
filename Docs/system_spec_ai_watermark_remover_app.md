# TÀI LIỆU THIẾT KẾ KIẾN TRÚC VÀ CẤU TẠO ỨNG DỤNG XÓA WATERMARK (AI-POWERED WATERMARK REMOVER)

---

## 1. TỔNG QUAN HỆ THỐNG (SYSTEM OVERVIEW)

Ứng dụng **AI Watermark Remover** là một hệ thống xử lý ảnh/video thông minh, hoạt động dựa trên cơ chế 2 bước chính (**2-Stage Pipeline**):
1. **Watermark Detection (Phát hiện Mask):** Nhận diện vùng watermark (chữ, logo, dấu bản quyền, caption) tự động bằng Vision Model (Florence-2 / SAM) hoặc thủ công qua công cụ Brush Canvas UI.
2. **AI Inpainting (Tái tạo vùng bị khuyết):** Sử dụng mạng Nơ-ron sâu **LaMa (Large Mask Inpainting)** kết hợp Fast Fourier Convolutions (FFC) để khôi phục cấu trúc và bề mặt điểm ảnh bên dưới lớp watermark mà không làm mờ (blur) hay biến dạng hình ảnh.

---

## 2. KIẾN TRÚC THUẬT TOÁN & CƠ CHẾ VẬN HÀNH (CORE ALGORITHMS)

### 2.1. Tiến trình xử lý (Processing Pipeline)
$$\text{Input Image } (I) \xrightarrow{\text{Detection / Brush}} \text{Binary Mask } (M) \xrightarrow{\text{LaMa Inpainting Engine}} \text{Clean Output } (\hat{I})$$

*   **Đầu vào:** 
    *   Ảnh gốc $I \in \mathbb{R}^{H \times W \times 3}$
    *   Vùng Mask $M \in \{0, 1\}^{H \times W}$ (Trong đó $M_{i,j} = 1$ đại diện cho vùng chứa Watermark cần xóa, $M_{i,j} = 0$ là vùng giữ nguyên).

### 2.2. Chi tiết Thuật toán

#### A. Thuật toán Nhận diện Mask Tự động (Automated Mask Detection)
*   **Mô hình:** `Microsoft Florence-2-base/large` hoặc `Grounding DINO + SAM (Segment Anything)`.
*   **Cơ chế:**
    1. Nhận prompt text mặc định: `"watermark, logo, text, stamp, caption"`.
    2. Xuất Bounding Box $B = [x_{min}, y_{min}, x_{max}, y_{max}]$.
    3. Chuyển đổi $B$ thành Binary Mask $M$ có mở rộng viền (Dilation kernel $k \times k$, thường $k=5px$) để bao trọn bóng mờ và viền anti-aliasing của watermark.

#### B. Thuật toán Khôi phục Pixel (LaMa - Large Mask Inpainting)
*   **Tại sao dùng LaMa?** Các mô hình CNN truyền thống thường bị mờ khi xóa các vùng watermark lớn. LaMa áp dụng **Fast Fourier Convolutions (FFC)** cho phép trường thụ cảm (receptive field) đạt mức toàn cục (global scope) ngay ở các tầng mạng đầu tiên, giúp học được các mẫu hoa văn tuần hoàn và kết cấu bề mặt phức tạp.
*   **Công thức tổng quát:**
    $$\hat{I} = I \odot (1 - M) + \mathcal{G}_{\theta}(I \odot (1 - M), M) \odot M$$
    *   Trong đó $\mathcal{G}_{\theta}$ là Generator Network của LaMa được tối ưu hóa qua Loss hàm Fourier và Adversarial Loss.

---

## 3. CẤU TRÚC HỆ THỐNG & CÔNG NGHỆ (TECH STACK)

### 3.1. Tech Stack Được Đề Xuất
*   **Frontend:** React.js / Next.js, TailwindCSS, HTML5 Canvas API / `konva` (để vẽ/chỉnh sửa Mask thủ công).
*   **Backend:** Python 3.10+, FastAPI, PyTorch, OpenCV, Pillow.
*   **AI Engine Models:**
    *   `LaMa TorchScript / ONNX Model` (Inpainting Engine - Siêu nhẹ, chạy được trên cả CPU & GPU).
    *   `Florence-2-base` (Auto Detection Model).
*   **Video Processing (Tùy chọn):** FFmpeg + OpenCV (xử lý từng frame ảnh & ghép lại âm thanh).

---

## 4. CẤU TRÚC MÃ NGUỒN DỰ ÁN (PROJECT STRUCTURE)

```text
watermark-remover/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI Web Entry
│   │   ├── config.py            # Cấu hình Model path, GPU/CPU device
│   │   ├── core/
│   │   │   ├── detector.py      # Florence-2 Watermark Detection logic
│   │   │   ├── inpainter.py     # LaMa Inpainting Engine execution
│   │   │   └── utils.py          # Processing Mask dilation, image formats
│   │   └── api/
│   │       └── routes.py        # REST API endpoints
│   ├── models/                  # Nơi chứa file weights (.ckpt / .onnx / .pt)
│   │   └── big-lama.pt
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ImageUploader.jsx
│   │   │   ├── MaskCanvas.jsx   # UI vẽ mask + preview so sánh Before/After
│   │   │   └── ControlPanel.jsx # Nút bấm Auto-Detect, Brush Size, Remove
│   │   ├── App.jsx
│   │   └── index.css
│   └── package.json
└── README.md
```

---

## 5. THIẾT KẾ REST API ENDPOINTS

### 1. Auto Detect Watermark Boundary
*   **Endpoint:** `POST /api/v1/detect`
*   **Payload:** `multipart/form-data` (file: Image File, prompt: string)
*   **Response:**
    ```json
    {
      "status": "success",
      "mask_base64": "data:image/png;base64,...",
      "bboxes": [[12, 45, 120, 80]]
    }
    ```

### 2. Inpaint / Remove Watermark
*   **Endpoint:** `POST /api/v1/inpaint`
*   **Payload:** `multipart/form-data` (image: Image File, mask: Mask Image File)
*   **Response:** ArrayBuffer / Blob (File ảnh PNG/WebP đã được xóa sạch watermark).

---

## 6. PROMPT MẪU CHO ANTIGRAVITY (MASTER PROMPT FOR GENERATION)

*Bạn có thể copy đoạn prompt bên dưới nạp vào Antigravity Agent để yêu cầu tự động khởi tạo dự án:*

```text
PROMPT CHO ANTIGRAVITY:

Hãy xây dựng trọn bộ dự án Web App xóa Watermark tự động bằng AI với tên gọi "AI Watermark Studio" theo kiến trúc sau:

1. BACKEND (Python FastAPI):
   - Xây dựng mô-đun `inpainter.py` nạp file mô hình TorchScript LaMa (`big-lama.pt`). Nhận vào ảnh đĩa/buffer (RGB) và ảnh Mask (Grayscale 0-255). Xuất ra ảnh đã khôi phục pixel.
   - Xây dựng mô-đun `detector.py` sử dụng thư viện `transformers` với mô hình `microsoft/Florence-2-base` để tự động dò tìm vị trí văn bản/logo watermark và trả về ảnh Mask binary.
   - Xây dựng FastAPI app trong `main.py` với các endpoints: `/api/v1/detect` và `/api/v1/inpaint`.
   - Hỗ trợ fallback: Nếu không phát hiện được watermark bằng AI, hệ thống cho phép chấp nhận mask do người dùng vẽ từ frontend.

2. FRONTEND (React + TailwindCSS + HTML5 Canvas):
   - Giao diện 2 cột/panel hiện đại: 
     + Cột trái: Tải ảnh, thanh công cụ Canvas Brush (chỉnh kích thước cọ vẽ, tẩy, nút 'Tự động phát hiện Watermark').
     + Cột phải: Xem kết quả so sánh Before/After slider (hoặc preview kết quả) và nút Download ảnh sạch.
   - Sử dụng HTML5 Canvas tương tác cho phép người dùng tô đè trực tiếp lên vùng watermark nếu muốn tinh chỉnh mask.

3. YÊU CẦU ĐẶC BIỆT:
   - Tự động thực hiện Dilation (nở mask) từ 3px - 5px trên OpenCV để triệt tiêu viền bóng mờ của watermark trước khi đưa vào LaMa Inpainting.
   - Viết mã nguồn sạch, chia nhỏ các hàm xử lý tensor và xử lý ảnh (PIL/OpenCV), sẵn sàng chạy trên cả CPU và CUDA GPU.
```