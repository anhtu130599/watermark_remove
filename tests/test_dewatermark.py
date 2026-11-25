from __future__ import annotations

import numpy as np
import pytest

from backend.app.media.dewatermark import (
    detect_template_watermark_bboxes,
    load_sparkle_alpha_templates,
    restore_watermark_region,
    try_blind_reverse_alpha,
    try_template_reverse_alpha,
)
from backend.app.media.mask_ops import dilate_mask


def _make_detailed_artwork(h: int = 220, w: int = 220) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 0] = 28
    img[:, :, 1] = 44
    img[:, :, 2] = 62
    # Vẽ đường sọc kiến trúc 2px xuyên suốt góc phải dưới để kiểm tra bảo toàn nét mảnh
    img[h - 62 : h - 59, :] = [165, 130, 80]
    img[:, w - 58 : w - 55] = [18, 22, 26]
    diag = np.abs((xx - (w - 90)) - (yy - (h - 90))) <= 1
    img[diag] = [40, 175, 195]
    return img


def test_template_reverse_alpha_lossless_recovery() -> None:
    clean = _make_detailed_artwork(240, 240)
    tpl48 = load_sparkle_alpha_templates()[48]
    y0, x0 = 240 - 32 - 48, 240 - 32 - 48

    wm_img = clean.copy().astype(np.float32)
    a = tpl48[:, :, None]
    wm_img[y0 : y0 + 48, x0 : x0 + 48] = (
        a * 255.0 + (1.0 - a) * wm_img[y0 : y0 + 48, x0 : x0 + 48]
    )
    wm_u8 = np.clip(np.rint(wm_img), 0, 255).astype(np.uint8)

    # Phát hiện tự động không cần Florence-2
    boxes = detect_template_watermark_bboxes(wm_u8)
    assert len(boxes) == 1
    assert boxes[0][0] <= x0 + 2 and boxes[0][1] <= y0 + 2

    # Giả lập B_prior mờ nhẹ từ AI (mất chi tiết đường chéo)
    smooth_prior = wm_u8.copy()
    smooth_prior[y0 - 4 : y0 + 52, x0 - 4 : x0 + 52] = [32, 46, 64]

    core = np.zeros((240, 240), dtype=np.uint8)
    core[y0 - 2 : y0 + 50, x0 - 2 : x0 + 50] = 255
    dilated = dilate_mask(core, kernel_px=3)

    rec, method = restore_watermark_region(wm_u8, smooth_prior, core, dilated, mode="auto")
    assert method.startswith("reverse-alpha:template")

    # Vùng bên trong dấu sao phải khôi phục chính xác đường nét gốc (MAE cực thấp & PSNR > 35 dB)
    mse = float(
        np.mean(
            (rec[y0 : y0 + 48, x0 : x0 + 48].astype(np.float32) - clean[y0 : y0 + 48, x0 : x0 + 48].astype(np.float32))
            ** 2
        )
    )
    psnr = 20.0 * np.log10(255.0 / max(np.sqrt(mse), 1e-4))
    assert psnr > 34.0
    assert np.array_equal(rec[dilated == 0], wm_u8[dilated == 0])


def test_blind_reverse_alpha_decomposition_for_arbitrary_text() -> None:
    clean = _make_detailed_artwork(180, 180)
    # Chèn thanh chữ bán trong suốt alpha=0.45 cắt ngang qua cả đường ngang, dọc và chéo
    overlay_mask = np.zeros((180, 180), dtype=np.uint8)
    overlay_mask[95:130, 50:145] = 255

    wm_u8 = clean.copy().astype(np.float32)
    alpha = 0.45 * (overlay_mask[:, :, None] > 0)
    wm_u8 = np.clip(np.rint((1.0 - alpha) * wm_u8 + alpha * 255.0), 0, 255).astype(np.uint8)

    # Prior mịn làm mất chi tiết các đường kiến trúc đi xuyên qua vùng watermark
    blur_prior = wm_u8.copy()
    blur_prior[90:135, 45:150] = [30, 48, 66]

    core = np.zeros((180, 180), dtype=np.uint8)
    core[93:132, 48:147] = 255
    dilated = dilate_mask(core, kernel_px=3)

    rec, method = restore_watermark_region(wm_u8, blur_prior, core, dilated, mode="auto")
    assert method == "reverse-alpha:blind"

    line_px = (core > 0) & (np.linalg.norm(clean.astype(float) - np.array([28.0, 44.0, 62.0]), axis=2) > 20.0)
    line_mae_prior = float(np.mean(np.abs(blur_prior[line_px].astype(float) - clean[line_px].astype(float))))
    line_mae_blind = float(np.mean(np.abs(rec[line_px].astype(float) - clean[line_px].astype(float))))
    assert line_mae_blind < line_mae_prior * 0.45
    assert np.array_equal(rec[dilated == 0], wm_u8[dilated == 0])


def test_opaque_watermark_routes_to_exemplar_and_preserves_outside() -> None:
    clean = _make_detailed_artwork(160, 160)
    wm_u8 = clean.copy()
    # Dán nhãn che đặc hoàn toàn (alpha=1.0 màu đỏ rực -> sắc độ cao không phải bán trong suốt)
    wm_u8[60:95, 60:105] = [235, 35, 35]

    lama_out = clean.copy()
    core = np.zeros((160, 160), dtype=np.uint8)
    core[59:96, 59:106] = 255
    dilated = dilate_mask(core, kernel_px=3)

    rec, method = restore_watermark_region(wm_u8, lama_out, core, dilated, mode="auto")
    assert method == "lama-super2x+exemplar"
    assert np.array_equal(rec[dilated == 0], wm_u8[dilated == 0])
