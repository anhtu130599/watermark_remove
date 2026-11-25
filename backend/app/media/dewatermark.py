from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

try:
    import cv2

    _HAS_CV2 = True
except ImportError:
    cv2 = None  # type: ignore[assignment]
    _HAS_CV2 = False

try:
    import torch
    import torch.nn.functional as F

    _HAS_TORCH = True
except ImportError:
    torch = None  # type: ignore[assignment]
    F = None  # type: ignore[assignment]
    _HAS_TORCH = False

from backend.app.media.mask_ops import composite_inpainted_region

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
VALID_DEWATERMARK_MODES = ("auto", "reverse_alpha", "inpaint")


def _analytic_sparkle_template(size: int) -> np.ndarray:
    """Fallback giải tích tạo mặt nạ alpha ngôi sao 4 cánh nếu thiếu tệp mẫu."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    c = (size - 1) / 2.0
    r = max(1.0, size * 0.42)
    dx = np.abs(xx - c) / r
    dy = np.abs(yy - c) / r
    # Đường cong Astroid (lũy thừa 0.55) mô phỏng hình ngôi sao 4 cánh bo nhọn
    d = np.power(np.maximum(dx, 1e-6), 0.55) + np.power(np.maximum(dy, 1e-6), 0.55)
    alpha = np.clip((1.0 - d) * 3.0, 0.0, 1.0) * 0.51
    return alpha.astype(np.float32)


@lru_cache(maxsize=1)
def load_sparkle_alpha_templates() -> dict[int, np.ndarray]:
    """Nạp bộ alpha map chuẩn (48x48 và 96x96) cho kỹ thuật Reverse Alpha Blending."""
    templates: dict[int, np.ndarray] = {}
    for size in (48, 96):
        path = _ASSETS_DIR / f"bg_{size}.png"
        if path.is_file():
            arr = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
            templates[size] = np.clip(np.max(arr, axis=2) / 255.0, 0.0, 1.0).astype(
                np.float32
            )
        else:
            templates[size] = _analytic_sparkle_template(size)
    return templates


def _resize_template(tpl: np.ndarray, size: int) -> np.ndarray:
    if tpl.shape[0] == size and tpl.shape[1] == size:
        return tpl
    if _HAS_CV2 and cv2 is not None:
        interp = cv2.INTER_AREA if size < tpl.shape[0] else cv2.INTER_LINEAR
        return cv2.resize(tpl, (size, size), interpolation=interp).astype(np.float32)
    pil = Image.fromarray(np.clip(tpl * 255.0, 0, 255).astype(np.uint8), mode="L")
    return np.asarray(pil.resize((size, size), Image.Resampling.BILINEAR), dtype=np.float32) / 255.0


def detect_template_watermark_bboxes(rgb_uint8: np.ndarray) -> list[list[int]]:
    """Phát hiện nhanh (<25ms) watermark bán trong suốt dạng ngôi sao 4 cánh ở góc dưới bên phải."""
    if not _HAS_CV2 or cv2 is None:
        return []

    h, w = rgb_uint8.shape[:2]
    if min(h, w) < 96:
        return []

    templates = load_sparkle_alpha_templates()
    base_tpl = templates[96]

    search_w = min(w, 240)
    search_h = min(h, 240)
    x0 = w - search_w
    y0 = h - search_h

    roi = rgb_uint8[y0:h, x0:w].astype(np.float32)
    bg_est = cv2.morphologyEx(
        roi.astype(np.uint8),
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21)),
    ).astype(np.float32)
    res_alpha = np.clip((roi - bg_est) / np.maximum(255.0 - bg_est, 25.0), 0.0, 1.0).mean(axis=2)

    best_score = -1.0
    best_box: list[int] | None = None

    candidate_sizes = [sz for sz in (40, 44, 48, 56, 64, 80, 96) if sz <= min(search_w, search_h) - 4]
    for sz in candidate_sizes:
        tpl = templates[sz] if sz in templates else _resize_template(base_tpl, sz)
        corr = cv2.matchTemplate(res_alpha, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_corr, _, max_loc = cv2.minMaxLoc(corr)
        if max_corr < 0.48:
            continue

        px, py = max_loc
        patch = res_alpha[py : py + sz, px : px + sz]
        inner_peak = float(np.percentile(patch[tpl > 0.25], 80)) if np.any(tpl > 0.25) else 0.0
        outer_base = float(np.median(patch[tpl < 0.02])) if np.any(tpl < 0.02) else 1.0
        contrast_lift = inner_peak - outer_base
        if contrast_lift < 0.16:
            continue

        score = float(max_corr) + 0.5 * contrast_lift
        if score > best_score:
            best_score = score
            bx1 = max(0, x0 + px - 2)
            by1 = max(0, y0 + py - 2)
            bx2 = min(w, x0 + px + sz + 2)
            by2 = min(h, y0 + py + sz + 2)
            best_box = [bx1, by1, bx2, by2]

    return [best_box] if best_box is not None else []


def _extract_mask_components(mask_uint8: np.ndarray) -> list[tuple[int, int, int, int]]:
    binary = (mask_uint8 > 127).astype(np.uint8)
    if not np.any(binary):
        return []
    if _HAS_CV2 and cv2 is not None:
        num_labels, _labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        boxes: list[tuple[int, int, int, int]] = []
        for idx in range(1, num_labels):
            x = int(stats[idx, cv2.CC_STAT_LEFT])
            y = int(stats[idx, cv2.CC_STAT_TOP])
            bw = int(stats[idx, cv2.CC_STAT_WIDTH])
            bh = int(stats[idx, cv2.CC_STAT_HEIGHT])
            if bw > 4 and bh > 4:
                boxes.append((x, y, x + bw, y + bh))
        return boxes
    ys, xs = np.where(binary > 0)
    return [(int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)]


def try_template_reverse_alpha(
    rgb_uint8: np.ndarray,
    lama_prior_rgb: np.ndarray,
    dilated_mask_uint8: np.ndarray,
    ncc_threshold: float = 0.72,
) -> tuple[np.ndarray | None, float]:
    """
    Tầng 1 (Tổn thất gần như 0): So khớp template alpha mẫu (48x48 / 96x96 đa tỷ lệ + sub-pixel)
    và giải phương trình I_orig = (I_wm - alpha * 255) / (1 - alpha) để phục hồi từng pixel gốc.
    """
    if not _HAS_CV2 or cv2 is None:
        return None, 0.0

    h, w = rgb_uint8.shape[:2]
    boxes = _extract_mask_components(dilated_mask_uint8)
    if not boxes:
        return None, 0.0

    templates = load_sparkle_alpha_templates()
    base_96 = templates[96]

    out = rgb_uint8.copy()
    matched_any = False
    best_overall_ncc = 0.0

    for x1, y1, x2, y2 in boxes:
        bw, bh = x2 - x1, y2 - y1
        # Chỉ thử so khớp template nếu mask có kích thước hợp lý cho logo góc (~24..160px)
        if max(bw, bh) < 20 or max(bw, bh) > 180:
            continue

        pad = 24
        wx1 = max(0, x1 - pad)
        wy1 = max(0, y1 - pad)
        wx2 = min(w, x2 + pad)
        wy2 = min(h, y2 + pad)
        win_w, win_h = wx2 - wx1, wy2 - wy1

        obs_win = rgb_uint8[wy1:wy2, wx1:wx2].astype(np.float32)
        pri_win = lama_prior_rgb[wy1:wy2, wx1:wx2].astype(np.float32)
        res_alpha = np.clip(
            (obs_win - pri_win) / np.maximum(255.0 - pri_win, 25.0),
            0.0,
            0.96,
        ).mean(axis=2)

        est_sz = int(round(max(bw, bh) * 0.85))
        cand_sizes = sorted(
            {
                sz
                for sz in list(range(max(28, est_sz - 20), min(min(win_w, win_h), est_sz + 24) + 1, 2))
                + [44, 48, 96]
                if 28 <= sz <= min(win_w, win_h)
            }
        )

        best_coarse = (-1.0, 0, 0, 0)
        for sz in cand_sizes:
            tpl = templates[sz] if sz in templates else _resize_template(base_96, sz)
            corr = cv2.matchTemplate(res_alpha, tpl, cv2.TM_CCOEFF_NORMED)
            _, mx, _, mloc = cv2.minMaxLoc(corr)
            if mx > best_coarse[0]:
                best_coarse = (float(mx), sz, int(mloc[0]), int(mloc[1]))

        coarse_ncc, best_sz, lx, ly = best_coarse
        if coarse_ncc < ncc_threshold:
            continue

        # Trích vùng chứa vừa khớp + 6px lề để tinh chỉnh tỷ lệ phân số (0.5px) và dịch chuyển sub-pixel
        margin = 6
        bx1 = max(0, wx1 + lx - margin)
        by1 = max(0, wy1 + ly - margin)
        bx2 = min(w, wx1 + lx + best_sz + margin)
        by2 = min(h, wy1 + ly + best_sz + margin)
        patch_w, patch_h = bx2 - bx1, by2 - by1
        cx_t = float((wx1 + lx) - bx1) + (best_sz - 1) / 2.0
        cy_t = float((wy1 + ly) - by1) + (best_sz - 1) / 2.0

        obs_box = rgb_uint8[by1:by2, bx1:bx2].astype(np.float32)
        pri_box = lama_prior_rgb[by1:by2, bx1:bx2].astype(np.float32)
        res_box = np.clip(
            (obs_box - pri_box) / np.maximum(255.0 - pri_box, 25.0),
            0.0,
            0.96,
        ).mean(axis=2)

        best_err = float("inf")
        best_alpha = np.zeros((patch_h, patch_w), dtype=np.float32)

        def _score_candidate(alpha_base: np.ndarray, is_exact: bool = False) -> None:
            nonlocal best_err, best_alpha
            active = alpha_base > 0.05
            if int(active.sum()) < 20:
                return
            plateau = alpha_base > 0.35
            gain = (
                float(np.clip(np.median(res_box[plateau] / alpha_base[plateau]), 0.85, 1.10))
                if int(plateau.sum()) >= 10
                else 1.0
            )
            if is_exact and abs(gain - 1.0) < 0.08:
                gain = 1.0
            alpha_cand = np.clip(alpha_base * gain, 0.0, 0.94)
            a3_cand = alpha_cand[:, :, None]
            raw_cand = np.where(
                a3_cand > 0.008,
                (obs_box - a3_cand * 255.0) / np.maximum(1.0 - a3_cand, 0.06),
                obs_box,
            )
            tv = float(
                np.abs(np.diff(raw_cand, axis=0)).mean()
                + np.abs(np.diff(raw_cand, axis=1)).mean()
            )
            neg_pen = float(np.maximum(0.0, -raw_cand).mean()) * 2.5
            err = tv + neg_pen
            if err < best_err:
                best_err = err
                best_alpha = alpha_cand

        # Kiểm tra chính xác bản mẫu gốc 48x48 / 96x96 trước (không resample nếu ảnh chuẩn lossless)
        if best_sz in templates:
            exact_canvas = np.zeros((patch_h, patch_w), dtype=np.float32)
            ox, oy = (wx1 + lx) - bx1, (wy1 + ly) - by1
            exact_canvas[oy : oy + best_sz, ox : ox + best_sz] = templates[best_sz]
            # Chấp nhận sai số nhỏ quanh vị trí chính xác
            for dy in (-0.5, 0.0, 0.5):
                for dx in (-0.5, 0.0, 0.5):
                    if dx == 0.0 and dy == 0.0:
                        _score_candidate(exact_canvas, is_exact=True)
                    else:
                        mat = np.float32([[1.0, 0.0, dx], [0.0, 1.0, dy]])
                        _score_candidate(
                            cv2.warpAffine(
                                exact_canvas,
                                mat,
                                (patch_w, patch_h),
                                flags=cv2.INTER_LINEAR,
                                borderValue=0.0,
                            )
                        )

        size_cands = [
            float(s)
            for s in np.linspace(max(24.0, best_sz - 3.0), min(float(min(patch_w, patch_h) - 2), best_sz + 3.0), 13)
        ]
        for cand_sz in size_cands:
            scale = cand_sz / 96.0
            for dy in (-0.75, -0.35, 0.0, 0.35, 0.75):
                for dx in (-0.75, -0.35, 0.0, 0.35, 0.75):
                    mat = np.float32(
                        [[scale, 0.0, cx_t + dx - 47.5 * scale], [0.0, scale, cy_t + dy - 47.5 * scale]]
                    )
                    shifted = cv2.warpAffine(
                        base_96,
                        mat,
                        (patch_w, patch_h),
                        flags=cv2.INTER_LINEAR,
                        borderValue=0.0,
                    )
                    _score_candidate(shifted)

        a3 = best_alpha[:, :, None]
        raw_unblended = (obs_box - a3 * 255.0) / np.maximum(1.0 - a3, 0.06)
        best_rec = np.where(a3 > 0.008, np.clip(raw_unblended, 0.0, 255.0), obs_box)

        # Chỉ chạy vá viền JPEG khi thực sự phát hiện âm pixel ((obs - alpha*255) < -0.5);
        # ảnh PNG khớp chính xác tuyệt đối được giữ nguyên kết quả đại số 100%.
        underflow = (best_alpha > 0.012) & (raw_unblended.min(axis=2) < -0.5)
        if int(underflow.sum()) >= 4:
            gx = cv2.Sobel(best_alpha, cv2.CV_32F, 1, 0, ksize=3)
            gy = cv2.Sobel(best_alpha, cv2.CV_32F, 0, 1, ksize=3)
            grad_mag = np.sqrt(gx * gx + gy * gy)
            rim_core = cv2.dilate(
                (grad_mag > 0.08).astype(np.uint8),
                np.ones((3, 3), np.uint8),
            ) > 0
            seed_u8 = np.clip(np.rint(best_rec), 0, 255).astype(np.uint8)
            rim_inpainted = cv2.inpaint(
                seed_u8, rim_core.astype(np.uint8) * 255, inpaintRadius=2, flags=cv2.INPAINT_TELEA
            ).astype(np.float32)
            rim_soft = cv2.GaussianBlur(rim_core.astype(np.float32), (3, 3), 0.8)[:, :, None]
            rec_final = best_rec * (1.0 - rim_soft) + rim_inpainted * rim_soft
        else:
            rec_final = best_rec

        local_mask = dilated_mask_uint8[by1:by2, bx1:bx2] > 127
        dst = out[by1:by2, bx1:bx2]
        dst[local_mask] = np.clip(np.rint(rec_final[local_mask]), 0, 255).astype(np.uint8)

        matched_any = True
        best_overall_ncc = max(best_overall_ncc, coarse_ncc)

    return (out, best_overall_ncc) if matched_any else (None, best_overall_ncc)


def _estimate_watermark_color(
    obs_f: np.ndarray,
    prior_f: np.ndarray,
    mask_bool: np.ndarray,
) -> np.ndarray:
    """Ước lượng màu chủ đạo W của watermark bán trong suốt (trắng, đen hoặc có màu)."""
    delta = (obs_f - prior_f)[mask_bool]
    pri_m = prior_f[mask_bool]
    if delta.shape[0] == 0:
        return np.array([255.0, 255.0, 255.0], dtype=np.float32)

    norms = np.linalg.norm(delta, axis=1)
    top_thr = max(10.0, float(np.percentile(norms, 82)))
    strong_idx = norms >= top_thr
    if int(strong_idx.sum()) < 8:
        strong_idx = norms >= float(np.median(norms))

    top_delta = delta[strong_idx]
    mean_d = top_delta.mean(axis=0)
    chroma_spread = float(np.max(mean_d) - np.min(mean_d))
    lum_shift = float(mean_d.mean())

    if chroma_spread < 18.0:
        if lum_shift >= 0.0:
            return np.array([255.0, 255.0, 255.0], dtype=np.float32)
        return np.array([0.0, 0.0, 0.0], dtype=np.float32)

    # Watermark có màu: ước lượng gần đúng màu bão hòa về hướng delta
    est_w = np.median(pri_m[strong_idx] + top_delta / 0.55, axis=0)
    return np.clip(est_w, 0.0, 255.0).astype(np.float32)


def try_blind_reverse_alpha(
    rgb_uint8: np.ndarray,
    lama_prior_rgb: np.ndarray,
    core_mask_uint8: np.ndarray,
    dilated_mask_uint8: np.ndarray,
    force: bool = False,
) -> np.ndarray | None:
    """
    Tầng 2 (Mọi chữ/logo bán trong suốt không cần mẫu trước):
    Tối ưu đồng thời nền gốc B và bản đồ độ mờ alpha theo I = (1-a)*B + a*W
    với neo tần số thấp từ LaMa B_prior giúp bảo toàn nét vẽ mảnh bên dưới.
    """
    if not _HAS_TORCH or torch is None or F is None:
        return None

    h, w = rgb_uint8.shape[:2]
    boxes = _extract_mask_components(dilated_mask_uint8)
    if not boxes:
        return None

    out = rgb_uint8.copy()
    applied_any = False

    for x1, y1, x2, y2 in boxes:
        pad = 24
        rx1 = max(0, x1 - pad)
        ry1 = max(0, y1 - pad)
        rx2 = min(w, x2 + pad)
        ry2 = min(h, y2 + pad)
        if (rx2 - rx1) * (ry2 - ry1) > 720 * 720:
            # Giới hạn kích thước tối đa để giữ tốc độ phản hồi nhanh trên CPU
            continue

        obs_crop = rgb_uint8[ry1:ry2, rx1:rx2].astype(np.float32)
        pri_crop = lama_prior_rgb[ry1:ry2, rx1:rx2].astype(np.float32)
        core_crop = core_mask_uint8[ry1:ry2, rx1:rx2] > 127
        dil_crop = dilated_mask_uint8[ry1:ry2, rx1:rx2] > 127
        eval_mask = core_crop if np.any(core_crop) else dil_crop

        W_col = _estimate_watermark_color(obs_crop, pri_crop, eval_mask)
        denom = W_col[None, None, :] - pri_crop
        valid_den = np.abs(denom) > 22.0
        alpha_ch = np.where(
            valid_den,
            (obs_crop - pri_crop) / np.where(valid_den, denom, 22.0),
            0.0,
        )
        alpha_ch = np.clip(alpha_ch, 0.0, 0.95)
        alpha_med = np.median(alpha_ch, axis=2) * dil_crop
        alpha_std = np.std(alpha_ch, axis=2)

        wm_active = (alpha_med > 0.06) & eval_mask
        if not force:
            if int(wm_active.sum()) < 20:
                continue
            med_std = float(np.median(alpha_std[wm_active]))
            p90_alpha = float(np.percentile(alpha_med[wm_active], 90))
            if med_std > 0.085 or p90_alpha > 0.85:
                # Watermark che đặc hoàn toàn (opaque) hoặc nhiễu sắc độ mạnh -> nhường tầng LaMa+Exemplar
                continue

        alpha_sm = (
            cv2.GaussianBlur(alpha_med.astype(np.float32), (0, 0), 2.2) * dil_crop
            if (_HAS_CV2 and cv2 is not None)
            else alpha_med.astype(np.float32)
        )
        safe_den_init = np.where(
            np.abs(W_col[None, None, :] - pri_crop) > 20.0,
            1.0 - alpha_sm[:, :, None],
            1.0,
        )
        b_init = np.clip(
            (obs_crop - alpha_sm[:, :, None] * W_col[None, None, :])
            / np.maximum(safe_den_init, 0.14),
            0.0,
            255.0,
        )
        b_init[~dil_crop] = obs_crop[~dil_crop]

        I_t = torch.from_numpy(obs_crop / 255.0).permute(2, 0, 1).unsqueeze(0)
        B0_t = torch.from_numpy(pri_crop / 255.0).permute(2, 0, 1).unsqueeze(0)
        M_t = torch.from_numpy(dil_crop.astype(np.float32)).unsqueeze(0).unsqueeze(0)
        W_t = torch.from_numpy((W_col / 255.0).reshape(1, 3, 1, 1))

        init_a = torch.from_numpy(np.clip(alpha_sm, 0.015, 0.88).astype(np.float32)).unsqueeze(0).unsqueeze(0)
        B_param = torch.nn.Parameter(torch.from_numpy(b_init / 255.0).permute(2, 0, 1).unsqueeze(0))
        A_logit = torch.nn.Parameter(torch.logit(init_a))
        opt = torch.optim.Adam(
            [{"params": [B_param], "lr": 0.015}, {"params": [A_logit], "lr": 0.04}]
        )

        def _low(z: "torch.Tensor") -> "torch.Tensor":
            return F.avg_pool2d(F.pad(z, (4, 4, 4, 4), mode="replicate"), 9, stride=1)

        with torch.enable_grad():
            for _ in range(70):
                opt.zero_grad()
                A = torch.sigmoid(A_logit) * M_t * 0.92
                B = B_param.clamp(0.0, 1.0)
                recon = (1.0 - A) * B + A * W_t
                loss_data = (
                    F.l1_loss(recon * M_t, I_t * M_t) * 25.0
                    + F.l1_loss(B * (1.0 - M_t), I_t * (1.0 - M_t)) * 20.0
                )
                loss_low = F.l1_loss(_low(B) * M_t, _low(B0_t) * M_t) * 5.0
                tv_a = (
                    torch.abs(A[:, :, :, :-1] - A[:, :, :, 1:]).mean()
                    + torch.abs(A[:, :, :-1, :] - A[:, :, 1:, :]).mean()
                ) * 3.0
                tv_b = (
                    torch.abs(B[:, :, :, :-1] - B[:, :, :, 1:]).mean()
                    + torch.abs(B[:, :, :-1, :] - B[:, :, 1:, :]).mean()
                ) * 0.55
                (loss_data + loss_low + tv_a + tv_b).backward()
                opt.step()

        B_np = (B_param.detach().clamp(0.0, 1.0).squeeze(0).permute(1, 2, 0).numpy() * 255.0)
        A_np = (torch.sigmoid(A_logit.detach()).squeeze(0).squeeze(0).numpy() * dil_crop * 0.92)

        # Ở phần người dùng tô dư mà alpha ~ 0 (< 0.015), giữ nguyên 100% ảnh gốc chưa đụng chạm
        clean_mask = (A_np < 0.015) & dil_crop
        B_np[clean_mask] = obs_crop[clean_mask]

        if _HAS_CV2 and cv2 is not None:
            gx = cv2.Sobel(A_np.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
            gy = cv2.Sobel(A_np.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
            edge_w = np.clip(np.sqrt(gx * gx + gy * gy) * 0.65, 0.0, 0.35)[:, :, None]
            B_np = B_np * (1.0 - edge_w) + pri_crop * edge_w

        dst = out[ry1:ry2, rx1:rx2]
        dst[dil_crop] = np.clip(np.rint(B_np[dil_crop]), 0, 255).astype(np.uint8)
        applied_any = True

    return out if applied_any else None


def refine_opaque_with_exemplars(
    rgb_uint8: np.ndarray,
    lama_rgb: np.ndarray,
    core_mask_uint8: np.ndarray,
    dilated_mask_uint8: np.ndarray,
    feather_px: int = 3,
) -> np.ndarray:
    """
    Tầng 3 (Watermark che đặc hoàn toàn): Tăng cường độ sắc nét & hạt vi mô từ ảnh lân cận
    bằng đối sánh vá 5x5 (Non-local high-frequency residual transfer) trước khi hòa biên mượt.
    """
    if not _HAS_CV2 or cv2 is None:
        return composite_inpainted_region(
            rgb_uint8, lama_rgb, dilated_mask_uint8, feather_px=feather_px, core_mask_uint8=core_mask_uint8
        )

    h, w = rgb_uint8.shape[:2]
    refined = lama_rgb.astype(np.float32).copy()
    boxes = _extract_mask_components(dilated_mask_uint8)

    for x1, y1, x2, y2 in boxes:
        if (x2 - x1) * (y2 - y1) > 360 * 360:
            continue
        pad = 36
        rx1, ry1 = max(0, x1 - pad), max(0, y1 - pad)
        rx2, ry2 = min(w, x2 + pad), min(h, y2 + pad)

        obs_roi = rgb_uint8[ry1:ry2, rx1:rx2].astype(np.float32)
        lam_roi = lama_rgb[ry1:ry2, rx1:rx2].astype(np.float32)
        msk_roi = dilated_mask_uint8[ry1:ry2, rx1:rx2] > 127

        # Chỉ dùng nguồn mẫu sạch nằm hoàn toàn ngoài vùng mask (erode valid source 2px để tránh mép mask)
        src_valid = ~cv2.dilate(msk_roi.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        rh, rw = msk_roi.shape
        if rh < 15 or rw < 15 or int(src_valid[2:-2, 2:-2].sum()) < 48:
            continue

        obs_hp = obs_roi - cv2.GaussianBlur(obs_roi, (0, 0), 1.2)
        lam_low = cv2.GaussianBlur(lam_roi, (0, 0), 1.5)
        obs_low = cv2.GaussianBlur(obs_roi, (0, 0), 1.5)

        src_ys, src_xs = np.where(src_valid[2 : rh - 2 : 2, 2 : rw - 2 : 2])
        src_ys = src_ys * 2 + 2
        src_xs = src_xs * 2 + 2
        if len(src_ys) < 24:
            continue
        if len(src_ys) > 700:
            step = max(1, len(src_ys) // 700)
            src_ys = src_ys[::step]
            src_xs = src_xs[::step]

        # Vector hóa đối sánh màu nền thấp (R, G, B 3x3 trung bình) theo batch nhỏ giữ RAM cực thấp
        src_feats = np.stack([obs_low[src_ys, src_xs, c] for c in range(3)], axis=1)  # (N_src, 3)
        dst_ys, dst_xs = np.where(msk_roi)
        if len(dst_ys) == 0:
            continue

        dst_feats = np.stack([lam_low[dst_ys, dst_xs, c] for c in range(3)], axis=1)  # (N_dst, 3)
        diff = dst_feats[:, None, :] - src_feats[None, :, :]
        dist2 = np.sum(diff * diff, axis=2)  # (N_dst, N_src)
        best_idx = np.argmin(dist2, axis=1)
        best_rmse = np.sqrt(dist2[np.arange(len(dst_ys)), best_idx] / 3.0)

        conf = np.where(best_rmse < 10.0, np.exp(-best_rmse / 7.5) * 0.45, 0.0)[:, None]
        matched_hp = obs_hp[src_ys[best_idx], src_xs[best_idx]]
        lam_hp = lam_roi[dst_ys, dst_xs] - lam_low[dst_ys, dst_xs]

        # Giữ nguyên cấu trúc thấp của LaMa, cộng phần hạt/chi tiết khớp tốt nhất từ nguồn thật xung quanh
        updated_px = np.clip(lam_roi[dst_ys, dst_xs] + conf * (matched_hp - lam_hp * 0.5), 0.0, 255.0)
        refined[ry1 + dst_ys, rx1 + dst_xs] = updated_px

    refined_u8 = np.clip(np.rint(refined), 0, 255).astype(np.uint8)
    return composite_inpainted_region(
        rgb_uint8,
        refined_u8,
        dilated_mask_uint8,
        feather_px=feather_px,
        core_mask_uint8=core_mask_uint8,
    )


def restore_watermark_region(
    rgb_uint8: np.ndarray,
    lama_rgb: np.ndarray,
    core_mask_uint8: np.ndarray,
    dilated_mask_uint8: np.ndarray,
    mode: str = "auto",
    feather_px: int = 3,
) -> tuple[np.ndarray, str]:
    """
    Bộ điều phối 3 tầng khôi phục watermark ít làm mất nét gốc nhất:
    1. `reverse-alpha:template`: Khớp mẫu alpha chuẩn & đảo ngược đại số 100% phi tuyến tính (lossless).
    2. `reverse-alpha:blind`: Tách lớp bán trong suốt tổng quát cho chữ/logo bất kỳ.
    3. `lama-super2x+exemplar`: Phục hồi che đặc hoàn toàn bằng LaMa ROI 2x + ghép chi tiết lân cận.
    """
    norm_mode = (mode or "auto").strip().lower()
    if norm_mode not in VALID_DEWATERMARK_MODES:
        norm_mode = "auto"

    if norm_mode in ("auto", "reverse_alpha"):
        tpl_out, ncc = try_template_reverse_alpha(rgb_uint8, lama_rgb, dilated_mask_uint8)
        if tpl_out is not None:
            tpl_out[dilated_mask_uint8 <= 127] = rgb_uint8[dilated_mask_uint8 <= 127]
            return np.ascontiguousarray(tpl_out), f"reverse-alpha:template(ncc={ncc:.2f})"

        blind_out = try_blind_reverse_alpha(
            rgb_uint8,
            lama_rgb,
            core_mask_uint8,
            dilated_mask_uint8,
            force=(norm_mode == "reverse_alpha"),
        )
        if blind_out is not None:
            blind_out[dilated_mask_uint8 <= 127] = rgb_uint8[dilated_mask_uint8 <= 127]
            return np.ascontiguousarray(blind_out), "reverse-alpha:blind"

    final_out = refine_opaque_with_exemplars(
        rgb_uint8,
        lama_rgb,
        core_mask_uint8,
        dilated_mask_uint8,
        feather_px=feather_px,
    )
    final_out[dilated_mask_uint8 <= 127] = rgb_uint8[dilated_mask_uint8 <= 127]
    return np.ascontiguousarray(final_out), "lama-super2x+exemplar"
