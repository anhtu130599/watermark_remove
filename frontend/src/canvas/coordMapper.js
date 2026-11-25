/**
 * Pure 1:1 coordinate transformation helpers mapping between client viewport
 * coordinates and native image pixels (`naturalWidth x naturalHeight`).
 */

export function clampValue(value, min, max) {
  if (Number.isNaN(value)) return min;
  return Math.min(Math.max(value, min), max);
}

/**
 * Compute centered fit scale & offsets so `naturalWidth x naturalHeight` fits
 * cleanly inside `containerWidth x containerHeight` with uniform padding.
 */
export function computeFitTransform({
  containerWidth,
  containerHeight,
  naturalWidth,
  naturalHeight,
  padding = 24,
}) {
  const cw = Number(containerWidth) || 0;
  const ch = Number(containerHeight) || 0;
  const nw = Number(naturalWidth) || 0;
  const nh = Number(naturalHeight) || 0;

  if (cw <= 0 || ch <= 0 || nw <= 0 || nh <= 0) {
    return { baseScale: 1, baseOffsetX: 0, baseOffsetY: 0 };
  }

  const usableW = Math.max(1, cw - padding * 2);
  const usableH = Math.max(1, ch - padding * 2);
  const baseScale = Math.min(usableW / nw, usableH / nh, 1);

  const renderedW = nw * baseScale;
  const renderedH = nh * baseScale;

  return {
    baseScale,
    baseOffsetX: (cw - renderedW) / 2,
    baseOffsetY: (ch - renderedH) / 2,
  };
}

export function getEffectiveScale(baseScale = 1, zoom = 1) {
  return Math.max(1e-6, (Number(baseScale) || 1) * (Number(zoom) || 1));
}

/**
 * Convert viewport client coordinates `(clientX, clientY)` to exact native image
 * pixel coordinates `(x, y)` regardless of zoom, pan, or devicePixelRatio.
 */
export function clientToImageCoords({
  clientX,
  clientY,
  rect,
  zoom = 1,
  panX = 0,
  panY = 0,
  baseScale = 1,
  baseOffsetX = 0,
  baseOffsetY = 0,
  naturalWidth,
  naturalHeight,
  clamp = true,
}) {
  const left = rect?.left ?? 0;
  const top = rect?.top ?? 0;
  const localX = clientX - left;
  const localY = clientY - top;

  const originX = (Number(baseOffsetX) || 0) + (Number(panX) || 0);
  const originY = (Number(baseOffsetY) || 0) + (Number(panY) || 0);
  const effectiveScale = getEffectiveScale(baseScale, zoom);

  const rawX = (localX - originX) / effectiveScale;
  const rawY = (localY - originY) / effectiveScale;

  const nw = Math.max(0, Number(naturalWidth) || 0);
  const nh = Math.max(0, Number(naturalHeight) || 0);
  const inside = rawX >= 0 && rawX <= nw && rawY >= 0 && rawY <= nh;

  return {
    x: clamp ? clampValue(rawX, 0, nw) : rawX,
    y: clamp ? clampValue(rawY, 0, nh) : rawY,
    rawX,
    rawY,
    inside,
  };
}

/**
 * Convert native image pixel coordinates `(x, y)` back into local canvas CSS
 * container offsets `(localX, localY)`.
 */
export function imageToClientOffset({
  x,
  y,
  zoom = 1,
  panX = 0,
  panY = 0,
  baseScale = 1,
  baseOffsetX = 0,
  baseOffsetY = 0,
}) {
  const effectiveScale = getEffectiveScale(baseScale, zoom);
  return {
    localX: (Number(baseOffsetX) || 0) + (Number(panX) || 0) + x * effectiveScale,
    localY: (Number(baseOffsetY) || 0) + (Number(panY) || 0) + y * effectiveScale,
  };
}

/**
 * Adjust zoom & pan around `(pivotLocalX, pivotLocalY)` so the image pixel
 * under the pointer stays pinned at the exact same viewport position.
 */
export function zoomAroundPoint({
  prevZoom,
  nextZoom,
  pivotLocalX,
  pivotLocalY,
  prevPanX = 0,
  prevPanY = 0,
  baseScale = 1,
  baseOffsetX = 0,
  baseOffsetY = 0,
  minZoom = 0.25,
  maxZoom = 8,
}) {
  const clampedZoom = clampValue(nextZoom, minZoom, maxZoom);
  const prevScale = getEffectiveScale(baseScale, prevZoom);
  const nextScale = getEffectiveScale(baseScale, clampedZoom);

  const imgX = (pivotLocalX - (baseOffsetX + prevPanX)) / prevScale;
  const imgY = (pivotLocalY - (baseOffsetY + prevPanY)) / prevScale;

  const panX = pivotLocalX - baseOffsetX - imgX * nextScale;
  const panY = pivotLocalY - baseOffsetY - imgY * nextScale;

  return { zoom: clampedZoom, panX, panY };
}

/**
 * Convert UI brush size (`5..150` screen px at fit scale) into native image
 * stroke diameter so mask strokes match visual thickness across image sizes.
 */
export function resolveImageBrushDiameter({ brushSize, baseScale = 1 }) {
  return Math.max(1, (Number(brushSize) || 1) / Math.max(1e-6, Number(baseScale) || 1));
}

/**
 * Compute CSS cursor ring diameter on screen for a given native brush diameter.
 */
export function resolveDisplayBrushDiameter({
  imageBrushDiameter,
  baseScale = 1,
  zoom = 1,
}) {
  return Math.max(2, imageBrushDiameter * getEffectiveScale(baseScale, zoom));
}
