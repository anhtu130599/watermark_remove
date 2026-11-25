from __future__ import annotations

import base64
from io import BytesIO

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError


class MediaValidationError(Exception):
    """Lỗi validation đầu vào ảnh/mask khớp chuẩn HTTP API Contract."""

    def __init__(self, message: str, status_code: int = 400, code: str = "BAD_REQUEST") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


def _detect_supported_magic(data: bytes) -> str | None:
    """Kiểm tra magic bytes thực tế, chỉ cho phép JPEG, PNG, WebP."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _open_validated_pil(data: bytes, max_size_mb: int, label: str = "image") -> Image.Image:
    """Kiểm tra dung lượng, magic bytes và mở ảnh đã chuẩn hóa EXIF."""
    if not data:
        raise MediaValidationError(f"File {label} rỗng.", status_code=400, code="BAD_REQUEST")

    max_bytes = max_size_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise MediaValidationError(
            f"Dung lượng file {label} vượt quá giới hạn {max_size_mb} MB.",
            status_code=413,
            code="PAYLOAD_TOO_LARGE",
        )

    if _detect_supported_magic(data) is None:
        raise MediaValidationError(
            f"Định dạng file {label} không được hỗ trợ (chỉ nhận JPEG, PNG, WebP).",
            status_code=415,
            code="UNSUPPORTED_MEDIA_TYPE",
        )

    try:
        img = Image.open(BytesIO(data))
        img.load()
        return ImageOps.exif_transpose(img)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise MediaValidationError(
            f"Không thể giải mã file {label}: {exc}",
            status_code=400,
            code="BAD_REQUEST",
        ) from exc


def validate_and_load_image(
    data: bytes, max_size_mb: int = 20, max_res_px: int = 4096
) -> tuple[np.ndarray, np.ndarray | None, tuple[int, int]]:
    """Đọc ảnh, chuẩn hóa EXIF, kiểm tra độ phân giải và tách riêng kênh Alpha nếu có."""
    img = _open_validated_pil(data, max_size_mb=max_size_mb, label="ảnh")
    orig_w, orig_h = img.size

    if max(orig_w, orig_h) > max_res_px:
        raise MediaValidationError(
            f"Kích thước ảnh ({orig_w}x{orig_h}) vượt quá giới hạn {max_res_px}px.",
            status_code=400,
            code="BAD_REQUEST",
        )

    has_alpha = img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info
    )
    if has_alpha:
        rgba = np.asarray(img.convert("RGBA"), dtype=np.uint8)
        rgb_uint8 = np.ascontiguousarray(rgba[:, :, :3])
        alpha_uint8 = np.ascontiguousarray(rgba[:, :, 3])
        return rgb_uint8, alpha_uint8, (orig_w, orig_h)

    rgb_uint8 = np.ascontiguousarray(np.asarray(img.convert("RGB"), dtype=np.uint8))
    return rgb_uint8, None, (orig_w, orig_h)


def load_mask_image(
    data: bytes, target_size: tuple[int, int], max_size_mb: int = 20
) -> np.ndarray:
    """Đọc ảnh mask (RGBA canvas trong suốt hoặc Grayscale đen-trắng) về nhị phân {0, 255}."""
    target_w, target_h = target_size
    if target_w <= 0 or target_h <= 0:
        raise MediaValidationError("Kích thước ảnh đích không hợp lệ.", 400, "BAD_REQUEST")

    img = _open_validated_pil(data, max_size_mb=max_size_mb, label="mask")
    mask_w, mask_h = img.size

    target_ratio = target_w / target_h
    mask_ratio = mask_w / mask_h
    if abs(target_ratio - mask_ratio) / max(target_ratio, 1e-6) > 0.05:
        raise MediaValidationError(
            f"Tỷ lệ mask ({mask_w}x{mask_h}) không khớp ảnh gốc ({target_w}x{target_h}).",
            status_code=400,
            code="MASK_DIMENSION_MISMATCH",
        )

    if (mask_w, mask_h) != (target_w, target_h):
        img = img.resize((target_w, target_h), Image.Resampling.NEAREST)

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = np.asarray(img.convert("RGBA"), dtype=np.uint8)
        alpha = rgba[:, :, 3]
        if np.any(alpha < 255):
            # Mask xuất từ canvas trong suốt: nét vẽ có alpha > 16
            binary = (alpha > 16).astype(np.uint8) * 255
            return np.ascontiguousarray(binary)

    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    binary = (gray > 127).astype(np.uint8) * 255
    return np.ascontiguousarray(binary)


def encode_png_with_alpha(
    rgb_uint8: np.ndarray, alpha_uint8: np.ndarray | None = None
) -> bytes:
    """Mã hóa ảnh RGB (kèm kênh Alpha gốc nếu có) thành PNG bytes."""
    if alpha_uint8 is not None:
        if alpha_uint8.shape[:2] != rgb_uint8.shape[:2]:
            raise ValueError("Kích thước kênh Alpha không khớp ảnh RGB.")
        rgba = np.dstack([rgb_uint8, alpha_uint8]).astype(np.uint8, copy=False)
        out_img = Image.fromarray(rgba, mode="RGBA")
    else:
        out_img = Image.fromarray(rgb_uint8.astype(np.uint8, copy=False), mode="RGB")

    buf = BytesIO()
    out_img.save(buf, format="PNG")
    return buf.getvalue()


def encode_mask_base64(mask_uint8: np.ndarray) -> str:
    """Mã hóa binary mask thành chuỗi data URI base64 PNG."""
    binary = ((mask_uint8 > 127).astype(np.uint8) * 255)
    buf = BytesIO()
    Image.fromarray(binary, mode="L").save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
