from __future__ import annotations

import base64
import sys
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.media import (
    MediaValidationError,
    bboxes_to_mask,
    composite_inpainted_region,
    dilate_mask,
    encode_mask_base64,
    encode_png_with_alpha,
    load_mask_image,
    validate_and_load_image,
)


def _to_bytes(img: Image.Image, fmt: str, **save_kwargs) -> bytes:
    buf = BytesIO()
    img.save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


def test_validate_and_load_formats_and_odd_dimensions() -> None:
    for fmt in ("JPEG", "PNG", "WEBP"):
        img = Image.new("RGB", (101, 77), color=(12, 120, 220))
        rgb, alpha, size = validate_and_load_image(_to_bytes(img, fmt))
        assert size == (101, 77)
        assert rgb.shape == (77, 101, 3)
        assert alpha is None


def test_exif_transpose_orientation_6() -> None:
    # Tạo ảnh 120x80 với nửa trên đỏ, nửa dưới xanh; gắn EXIF Orientation=6 (xoay 90 CW -> 80x120)
    raw = Image.new("RGB", (120, 80), color=(0, 0, 255))
    for y in range(40):
        for x in range(120):
            raw.putpixel((x, y), (255, 0, 0))

    exif = Image.Exif()
    exif[0x0112] = 6  # Rotate 270 CW / 90 CW display
    data = _to_bytes(raw, "JPEG", exif=exif, quality=95)

    rgb, alpha, size = validate_and_load_image(data)
    assert alpha is None
    assert size == (80, 120)
    assert rgb.shape == (120, 80, 3)
    # Sau khi xoay 90 CW, nửa trên màu đỏ nằm ở phía bên phải (cột x >= 40)
    assert rgb[10, 65, 0] > 200
    assert rgb[10, 10, 2] > 200


def test_png_alpha_preservation_round_trip() -> None:
    rgba = np.zeros((40, 60, 4), dtype=np.uint8)
    rgba[:, :, :3] = [30, 150, 210]
    rgba[:20, :, 3] = 0
    rgba[20:30, :, 3] = 128
    rgba[30:, :, 3] = 255
    data = _to_bytes(Image.fromarray(rgba, mode="RGBA"), "PNG")

    rgb, alpha, size = validate_and_load_image(data)
    assert size == (60, 40)
    assert alpha is not None
    assert np.array_equal(alpha, rgba[:, :, 3])

    out_bytes = encode_png_with_alpha(rgb, alpha)
    out_img = Image.open(BytesIO(out_bytes))
    assert out_img.mode == "RGBA"
    assert np.array_equal(np.asarray(out_img), rgba)


def test_validation_errors() -> None:
    with pytest.raises(MediaValidationError) as exc_empty:
        validate_and_load_image(b"")
    assert exc_empty.value.status_code == 400

    with pytest.raises(MediaValidationError) as exc_magic:
        validate_and_load_image(b"GIF89a\x01\x00\x01\x00\x00\x00\x00;")
    assert exc_magic.value.status_code == 415

    big_png = _to_bytes(Image.new("RGB", (200, 200), (1, 2, 3)), "PNG")
    with pytest.raises(MediaValidationError) as exc_size:
        validate_and_load_image(big_png, max_size_mb=0)
    assert exc_size.value.status_code == 413

    with pytest.raises(MediaValidationError) as exc_res:
        validate_and_load_image(big_png, max_res_px=150)
    assert exc_res.value.status_code == 400


def test_bboxes_and_dilate_mask() -> None:
    mask = bboxes_to_mask([[-5, 10, 25, 20], [50, 40, 40, 30]], width=60, height=50)
    assert mask.shape == (50, 60)
    assert mask[15, 0] == 255
    assert mask[35, 45] == 255
    assert mask[0, 0] == 0

    d0 = dilate_mask(mask, kernel_px=0)
    assert np.array_equal(d0, mask)

    point = np.zeros((31, 31), dtype=np.uint8)
    point[15, 15] = 255
    for radius in (3, 5):
        dilated = dilate_mask(point, kernel_px=radius)
        assert dilated[15, 15 + radius] == 255
        assert dilated[15, 15 + radius + 1] == 0


def test_load_mask_both_canvas_alpha_and_grayscale() -> None:
    # 1. Canvas transparent PNG
    canvas_rgba = np.zeros((40, 80, 4), dtype=np.uint8)
    canvas_rgba[10:20, 20:40] = [255, 0, 0, 200]
    m1 = load_mask_image(_to_bytes(Image.fromarray(canvas_rgba, mode="RGBA"), "PNG"), (80, 40))
    assert m1.shape == (40, 80)
    assert m1[15, 30] == 255
    assert m1[0, 0] == 0

    # 2. Binary grayscale mask (resize nhẹ giữ tỷ lệ)
    gray = np.zeros((20, 40), dtype=np.uint8)
    gray[5:10, 10:20] = 255
    m2 = load_mask_image(_to_bytes(Image.fromarray(gray, mode="L"), "PNG"), (80, 40))
    assert m2[15, 30] == 255
    assert m2[0, 0] == 0

    # 3. Sai tỷ lệ khung hình -> 400
    wrong_ratio = _to_bytes(Image.new("L", (40, 40), 255), "PNG")
    with pytest.raises(MediaValidationError) as exc_ratio:
        load_mask_image(wrong_ratio, (80, 40))
    assert exc_ratio.value.code == "MASK_DIMENSION_MISMATCH"


def test_composite_preserves_outside_pixels_and_base64() -> None:
    orig = np.full((30, 30, 3), 42, dtype=np.uint8)
    inpainted = np.full((30, 30, 3), 200, dtype=np.uint8)
    mask = np.zeros((30, 30), dtype=np.uint8)
    mask[10:20, 10:20] = 255

    out = composite_inpainted_region(orig, inpainted, mask, feather_px=2)
    assert np.all(out[0:10, :] == 42)
    assert np.all(out[13:17, 13:17] == 200)

    uri = encode_mask_base64(mask)
    assert uri.startswith("data:image/png;base64,")
    raw_png = base64.b64decode(uri.split(",", 1)[1])
    assert Image.open(BytesIO(raw_png)).size == (30, 30)


def test_composite_smooth_feather_and_core_mask_preservation() -> None:
    orig = np.full((60, 60, 3), 20, dtype=np.uint8)
    inpainted = np.full((60, 60, 3), 220, dtype=np.uint8)
    core = np.zeros((60, 60), dtype=np.uint8)
    core[24:36, 24:36] = 255
    dilated = dilate_mask(core, kernel_px=6)

    out = composite_inpainted_region(
        orig, inpainted, dilated, feather_px=6, core_mask_uint8=core
    )
    # Ngoài mask giữ nguyên 100%
    assert np.all(out[dilated == 0] == 20)
    # Trong core giữ nguyên phần tái tạo (gần 220, không bóng ma ảnh gốc)
    assert int(out[30, 30, 0]) >= 215
    # Vùng vành đai chuyển tiếp phải có giá trị trung gian mượt (0 < alpha < 1), không cắt cứng 220!
    edge_val = int(out[19, 30, 0])
    assert 20 < edge_val < 200
