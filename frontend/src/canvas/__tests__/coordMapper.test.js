import { describe, expect, it } from "vitest";
import {
  clientToImageCoords,
  computeFitTransform,
  imageToClientOffset,
  resolveDisplayBrushDiameter,
  resolveImageBrushDiameter,
  zoomAroundPoint,
} from "../coordMapper";

describe("coordMapper", () => {
  it("centers landscape, portrait, and odd-sized images within container", () => {
    const landscape = computeFitTransform({
      containerWidth: 1000,
      containerHeight: 800,
      naturalWidth: 1920,
      naturalHeight: 1080,
      padding: 20,
    });
    expect(landscape.baseScale).toBeCloseTo(960 / 1920, 6);
    expect(landscape.baseOffsetX).toBeCloseTo(20, 6);
    expect(landscape.baseOffsetY).toBeCloseTo((800 - 1080 * landscape.baseScale) / 2, 6);

    const portrait = computeFitTransform({
      containerWidth: 1000,
      containerHeight: 800,
      naturalWidth: 1080,
      naturalHeight: 1920,
      padding: 20,
    });
    expect(portrait.baseScale).toBeCloseTo(760 / 1920, 6);
    expect(portrait.baseOffsetY).toBeCloseTo(20, 6);

    const oddSmall = computeFitTransform({
      containerWidth: 1200,
      containerHeight: 900,
      naturalWidth: 733,
      naturalHeight: 511,
      padding: 24,
    });
    expect(oddSmall.baseScale).toBe(1);
    expect(oddSmall.baseOffsetX).toBeCloseTo((1200 - 733) / 2, 6);
    expect(oddSmall.baseOffsetY).toBeCloseTo((900 - 511) / 2, 6);
  });

  it("performs exact 1:1 roundtrip across zooms, pans, and CSS rect offsets", () => {
    const fit = computeFitTransform({
      containerWidth: 900,
      containerHeight: 600,
      naturalWidth: 1920,
      naturalHeight: 1080,
      padding: 24,
    });
    const rect = { left: 132.5, top: 78.25 };

    for (const zoom of [0.5, 1, 2.75, 6]) {
      const panX = -45.5;
      const panY = 32.25;
      const targetImg = { x: 1234.5, y: 678.25 };

      const offset = imageToClientOffset({
        ...targetImg,
        zoom,
        panX,
        panY,
        ...fit,
      });

      const mapped = clientToImageCoords({
        clientX: rect.left + offset.localX,
        clientY: rect.top + offset.localY,
        rect,
        zoom,
        panX,
        panY,
        ...fit,
        naturalWidth: 1920,
        naturalHeight: 1080,
      });

      expect(mapped.inside).toBe(true);
      expect(mapped.x).toBeCloseTo(targetImg.x, 5);
      expect(mapped.y).toBeCloseTo(targetImg.y, 5);
    }
  });

  it("clamps out-of-bounds coordinates when clamp=true and preserves raw values when false", () => {
    const fit = { baseScale: 0.5, baseOffsetX: 100, baseOffsetY: 50 };
    const rect = { left: 10, top: 20 };

    const clamped = clientToImageCoords({
      clientX: 10,
      clientY: 20,
      rect,
      ...fit,
      naturalWidth: 800,
      naturalHeight: 600,
      clamp: true,
    });
    expect(clamped.inside).toBe(false);
    expect(clamped.x).toBe(0);
    expect(clamped.y).toBe(0);
    expect(clamped.rawX).toBeLessThan(0);

    const unclamped = clientToImageCoords({
      clientX: 900,
      clientY: 700,
      rect,
      ...fit,
      naturalWidth: 800,
      naturalHeight: 600,
      clamp: false,
    });
    expect(unclamped.inside).toBe(false);
    expect(unclamped.x).toBeGreaterThan(800);
    expect(unclamped.y).toBeGreaterThan(600);
  });

  it("keeps the image point under the pointer fixed during zoomAroundPoint", () => {
    const fit = { baseScale: 0.45, baseOffsetX: 40, baseOffsetY: 30 };
    const pivotLocalX = 420;
    const pivotLocalY = 290;
    const prevZoom = 1.25;
    const prevPanX = -18;
    const prevPanY = 24;

    const before = clientToImageCoords({
      clientX: pivotLocalX,
      clientY: pivotLocalY,
      rect: { left: 0, top: 0 },
      zoom: prevZoom,
      panX: prevPanX,
      panY: prevPanY,
      ...fit,
      naturalWidth: 1920,
      naturalHeight: 1080,
      clamp: false,
    });

    const next = zoomAroundPoint({
      prevZoom,
      nextZoom: 3.1,
      pivotLocalX,
      pivotLocalY,
      prevPanX,
      prevPanY,
      ...fit,
    });

    const after = clientToImageCoords({
      clientX: pivotLocalX,
      clientY: pivotLocalY,
      rect: { left: 0, top: 0 },
      zoom: next.zoom,
      panX: next.panX,
      panY: next.panY,
      ...fit,
      naturalWidth: 1920,
      naturalHeight: 1080,
      clamp: false,
    });

    expect(after.x).toBeCloseTo(before.x, 5);
    expect(after.y).toBeCloseTo(before.y, 5);
  });

  it("scales brush diameter consistently between screen and native coordinates", () => {
    const nativeDiameter = resolveImageBrushDiameter({ brushSize: 40, baseScale: 0.5 });
    expect(nativeDiameter).toBe(80);
    expect(
      resolveDisplayBrushDiameter({ imageBrushDiameter: nativeDiameter, baseScale: 0.5, zoom: 2 })
    ).toBe(80);
  });
});
