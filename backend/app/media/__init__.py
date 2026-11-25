"""Media & Image Processing Package (IMediaProcessor)."""

from .dewatermark import (
    VALID_DEWATERMARK_MODES,
    detect_template_watermark_bboxes,
    restore_watermark_region,
)
from .image_io import (
    MediaValidationError,
    encode_mask_base64,
    encode_png_with_alpha,
    load_mask_image,
    validate_and_load_image,
)
from .mask_ops import bboxes_to_mask, composite_inpainted_region, dilate_mask

__all__ = [
    "MediaValidationError",
    "VALID_DEWATERMARK_MODES",
    "validate_and_load_image",
    "load_mask_image",
    "encode_png_with_alpha",
    "encode_mask_base64",
    "bboxes_to_mask",
    "dilate_mask",
    "composite_inpainted_region",
    "detect_template_watermark_bboxes",
    "restore_watermark_region",
]
