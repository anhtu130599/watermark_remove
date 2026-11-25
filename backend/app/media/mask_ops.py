from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    cv2 = None  # type: ignore[assignment]
    _HAS_CV2 = False


def bboxes_to_mask(
    bboxes: list[list[int | float]], width: int, height: int
) -> np.ndarray:
    """Chuyển danh sách bounding box [x1, y1, x2, y2] thành binary mask {0, 255}."""
    if width <= 0 or height <= 0:
        raise ValueError("Chiều rộng và chiều cao mask phải dương.")

    mask = np.zeros((height, width), dtype=np.uint8)
    for box in bboxes:
        if len(box) < 4:
            continue
        raw_x1, raw_y1, raw_x2, raw_y2 = box[:4]
        x1 = max(0, min(width, int(np.floor(min(raw_x1, raw_x2)))))
        x2 = max(0, min(width, int(np.ceil(max(raw_x1, raw_x2)))))
        y1 = max(0, min(height, int(np.floor(min(raw_y1, raw_y2)))))
        y2 = max(0, min(height, int(np.ceil(max(raw_y1, raw_y2)))))
        if x2 > x1 and y2 > y1:
            mask[y1:y2, x1:x2] = 255
    return mask


def dilate_mask(mask_uint8: np.ndarray, kernel_px: int = 5) -> np.ndarray:
    """Nở vùng mask theo bán kính kernel_px (0..25px) để bao trọn viền bóng mờ."""
    if kernel_px < 0 or kernel_px > 25:
        raise ValueError("kernel_px phải nằm trong khoảng 0..25.")

    binary = ((mask_uint8 > 127).astype(np.uint8) * 255)
    if kernel_px == 0 or not np.any(binary):
        return np.ascontiguousarray(binary)

    ksize = 2 * kernel_px + 1
    if _HAS_CV2 and cv2 is not None:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
        dilated = cv2.dilate(binary, kernel, iterations=1)
        return np.ascontiguousarray((dilated > 127).astype(np.uint8) * 255)

    # Fallback bằng Pillow khi thiếu OpenCV
    pil_mask = Image.fromarray(binary, mode="L").filter(ImageFilter.MaxFilter(size=ksize))
    arr = np.asarray(pil_mask, dtype=np.uint8)
    return np.ascontiguousarray((arr > 127).astype(np.uint8) * 255)


def composite_inpainted_region(
    original_rgb: np.ndarray,
    inpainted_rgb: np.ndarray,
    mask_uint8: np.ndarray,
    feather_px: int = 2,
    core_mask_uint8: np.ndarray | None = None,
) -> np.ndarray:
    """Trộn ảnh tái tạo vào vùng mask với hòa sắc/độ hạt xung quanh và biên chuyển mượt, giữ 100% pixel ngoài mask."""
    if original_rgb.shape != inpainted_rgb.shape:
        raise ValueError("Kích thước ảnh gốc và ảnh tái tạo không khớp.")
    if mask_uint8.shape[:2] != original_rgb.shape[:2]:
        raise ValueError("Kích thước mask không khớp ảnh gốc.")

    binary_bool = mask_uint8 > 127
    if not np.any(binary_bool):
        return np.ascontiguousarray(original_rgb.copy())

    orig_f = original_rgb.astype(np.float32)
    inp_f = inpainted_rgb.astype(np.float32)
    binary_u8 = binary_bool.astype(np.uint8)
    binary = binary_u8.astype(np.float32)

    if feather_px > 0 and _HAS_CV2 and cv2 is not None:
        # 1. Cân chỉnh nhẹ sắc độ & độ sắc nét vi mô theo vòng nền sạch liền kề để tránh "vết sẹo" phẳng
        ring_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        outer_ring = (cv2.dilate(binary_u8, ring_kernel, iterations=1) > 0) & (~binary_bool)
        inner_ring = binary_bool & (cv2.erode(binary_u8, ring_kernel, iterations=1) == 0)

        if int(outer_ring.sum()) >= 16 and int(inner_ring.sum()) >= 16:
            raw_shift = np.median(orig_f[outer_ring], axis=0) - np.median(inp_f[inner_ring], axis=0)
            if float(np.max(np.abs(raw_shift))) <= 15.0:
                shift = np.clip(raw_shift, -8.0, 8.0)
                inp_f = np.clip(inp_f + 0.65 * shift, 0.0, 255.0)

            orig_hp = orig_f - cv2.GaussianBlur(orig_f, (0, 0), sigmaX=1.0)
            inp_hp = inp_f - cv2.GaussianBlur(inp_f, (0, 0), sigmaX=1.0)
            outer_mad = float(np.median(np.abs(orig_hp[outer_ring])))
            inner_mad = float(np.median(np.abs(inp_hp[binary_bool])))
            if inner_mad > 0.2 and outer_mad > inner_mad:
                gain = float(np.clip(outer_mad / inner_mad, 1.0, 1.30))
                inp_f = np.clip((inp_f - inp_hp) + inp_hp * gain, 0.0, 255.0)

        # 2. Chuyển tiếp Cosine mượt theo distance transform (hỗ trợ vùng lõi core_mask 100% không bóng ma)
        dist_out = cv2.distanceTransform(binary_u8, cv2.DIST_L2, 5)
        if core_mask_uint8 is not None and core_mask_uint8.shape[:2] == binary_u8.shape and np.any(core_mask_uint8 > 127):
            core_u8 = ((core_mask_uint8 > 127) & binary_bool).astype(np.uint8)
            dist_core = cv2.distanceTransform((1 - core_u8).astype(np.uint8), cv2.DIST_L2, 5)
            t = np.where(
                core_u8 > 0,
                1.0,
                dist_out / np.maximum(dist_out + dist_core, 1e-5),
            )
        else:
            t = np.clip((dist_out - 0.5) / float(max(1, feather_px)), 0.0, 1.0)

        ramp = np.clip(t, 0.0, 1.0)
        alpha = np.where(binary_bool, 0.5 - 0.5 * np.cos(np.pi * ramp), 0.0).astype(np.float32)
    else:
        alpha = binary

    alpha_3d = alpha[:, :, None]
    blended = orig_f * (1.0 - alpha_3d) + inp_f * alpha_3d
    out = np.clip(np.rint(blended), 0, 255).astype(np.uint8)
    # Bảo đảm cứng các pixel ngoài mask giữ nguyên từng bit của ảnh gốc
    out[~binary_bool] = original_rgb[~binary_bool]
    return np.ascontiguousarray(out)
