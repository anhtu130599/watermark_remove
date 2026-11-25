import React, {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { Minus, Plus, RotateCcw } from "lucide-react";
import {
  clientToImageCoords,
  computeFitTransform,
  getEffectiveScale,
  resolveDisplayBrushDiameter,
  resolveImageBrushDiameter,
  zoomAroundPoint,
} from "./coordMapper";
import { useCanvasHistory } from "./useCanvasHistory";

const MASK_PAINT_COLOR = "#f43f5e";

const MaskCanvas = forwardRef(function MaskCanvas(
  {
    imageUrl,
    aiMaskBase64 = null,
    aiMaskVersion = 0,
    tool = "brush",
    brushSize = 36,
    maskOpacity = 0.55,
    onHistoryChange,
    onMaskChange,
    className = "",
  },
  ref
) {
  const containerRef = useRef(null);
  const displayCanvasRef = useRef(null);
  const imageRef = useRef(null);
  const maskCanvasRef = useRef(null);
  const tintCanvasRef = useRef(null);

  const viewRef = useRef({
    containerWidth: 0,
    containerHeight: 0,
    baseScale: 1,
    baseOffsetX: 0,
    baseOffsetY: 0,
    zoom: 1,
    panX: 0,
    panY: 0,
  });

  const drawingRef = useRef({
    active: false,
    mode: null, // 'brush' | 'eraser' | 'pan'
    lastImgPoint: null,
    lastClientPoint: null,
    strokeChanged: false,
  });

  const cursorRef = useRef({ visible: false, localX: 0, localY: 0 });
  const spaceHeldRef = useRef(false);
  const appliedAiKeyRef = useRef("");

  const [imageDims, setImageDims] = useState({ width: 0, height: 0 });
  const [zoomPercent, setZoomPercent] = useState(100);

  const {
    canUndo,
    canRedo,
    hasMask,
    initHistory,
    pushSnapshot,
    undoSnapshot,
    redoSnapshot,
  } = useCanvasHistory(20);

  const hasMaskRef = useRef(hasMask);
  hasMaskRef.current = hasMask;

  useEffect(() => {
    onHistoryChange?.({ canUndo, canRedo, hasMask });
    onMaskChange?.(hasMask);
  }, [canUndo, canRedo, hasMask, onHistoryChange, onMaskChange]);

  const refreshTintBuffer = useCallback(() => {
    const maskCanvas = maskCanvasRef.current;
    if (!maskCanvas) return null;

    let tintCanvas = tintCanvasRef.current;
    if (!tintCanvas) {
      tintCanvas = document.createElement("canvas");
      tintCanvasRef.current = tintCanvas;
    }
    if (tintCanvas.width !== maskCanvas.width || tintCanvas.height !== maskCanvas.height) {
      tintCanvas.width = maskCanvas.width;
      tintCanvas.height = maskCanvas.height;
    }

    const tCtx = tintCanvas.getContext("2d");
    tCtx.clearRect(0, 0, tintCanvas.width, tintCanvas.height);
    tCtx.globalCompositeOperation = "source-over";
    tCtx.drawImage(maskCanvas, 0, 0);
    tCtx.globalCompositeOperation = "source-in";
    tCtx.fillStyle = MASK_PAINT_COLOR;
    tCtx.fillRect(0, 0, tintCanvas.width, tintCanvas.height);
    tCtx.globalCompositeOperation = "source-over";
    return tintCanvas;
  }, []);

  const renderCanvas = useCallback(() => {
    const displayCanvas = displayCanvasRef.current;
    const img = imageRef.current;
    const view = viewRef.current;
    if (!displayCanvas || view.containerWidth <= 0 || view.containerHeight <= 0) {
      return;
    }

    const dpr = window.devicePixelRatio || 1;
    const targetW = Math.max(1, Math.round(view.containerWidth * dpr));
    const targetH = Math.max(1, Math.round(view.containerHeight * dpr));
    if (displayCanvas.width !== targetW || displayCanvas.height !== targetH) {
      displayCanvas.width = targetW;
      displayCanvas.height = targetH;
    }

    const ctx = displayCanvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, view.containerWidth, view.containerHeight);

    if (!img) return;

    const effScale = getEffectiveScale(view.baseScale, view.zoom);
    const drawX = view.baseOffsetX + view.panX;
    const drawY = view.baseOffsetY + view.panY;
    const drawW = img.naturalWidth * effScale;
    const drawH = img.naturalHeight * effScale;

    ctx.save();
    ctx.imageSmoothingEnabled = effScale < 2;
    ctx.drawImage(img, drawX, drawY, drawW, drawH);

    const tintCanvas = tintCanvasRef.current;
    if (tintCanvas && tintCanvas.width > 0 && tintCanvas.height > 0) {
      ctx.globalAlpha = maskOpacity;
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(tintCanvas, drawX, drawY, drawW, drawH);
      ctx.globalAlpha = 1;
    }

    ctx.strokeStyle = "rgba(148, 163, 184, 0.35)";
    ctx.lineWidth = 1;
    ctx.strokeRect(drawX, drawY, drawW, drawH);
    ctx.restore();

    if (
      cursorRef.current.visible &&
      tool !== "pan" &&
      !spaceHeldRef.current &&
      drawingRef.current.mode !== "pan"
    ) {
      const imgDiameter = resolveImageBrushDiameter({
        brushSize,
        baseScale: view.baseScale,
      });
      const displayDiameter = resolveDisplayBrushDiameter({
        imageBrushDiameter: imgDiameter,
        baseScale: view.baseScale,
        zoom: view.zoom,
      });
      ctx.save();
      ctx.beginPath();
      ctx.arc(
        cursorRef.current.localX,
        cursorRef.current.localY,
        displayDiameter / 2,
        0,
        Math.PI * 2
      );
      ctx.strokeStyle = tool === "eraser" ? "#38bdf8" : "#ffffff";
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(
        cursorRef.current.localX,
        cursorRef.current.localY,
        Math.max(1, displayDiameter / 2 - 1),
        0,
        Math.PI * 2
      );
      ctx.strokeStyle = "rgba(15, 23, 42, 0.7)";
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.restore();
    }
  }, [brushSize, maskOpacity, tool]);

  const recalcFitTransform = useCallback(
    (resetZoom = false) => {
      const container = containerRef.current;
      const img = imageRef.current;
      if (!container) return;

      const rect = container.getBoundingClientRect();
      viewRef.current.containerWidth = rect.width;
      viewRef.current.containerHeight = rect.height;

      if (img && img.naturalWidth > 0 && img.naturalHeight > 0) {
        const fit = computeFitTransform({
          containerWidth: rect.width,
          containerHeight: rect.height,
          naturalWidth: img.naturalWidth,
          naturalHeight: img.naturalHeight,
          padding: 24,
        });
        viewRef.current.baseScale = fit.baseScale;
        viewRef.current.baseOffsetX = fit.baseOffsetX;
        viewRef.current.baseOffsetY = fit.baseOffsetY;
      }

      if (resetZoom) {
        viewRef.current.zoom = 1;
        viewRef.current.panX = 0;
        viewRef.current.panY = 0;
        setZoomPercent(100);
      }

      renderCanvas();
    },
    [renderCanvas]
  );

  // Load main image & initialize native offscreen mask canvas
  useEffect(() => {
    if (!imageUrl) {
      imageRef.current = null;
      maskCanvasRef.current = null;
      tintCanvasRef.current = null;
      appliedAiKeyRef.current = "";
      setImageDims({ width: 0, height: 0 });
      initHistory(null);
      renderCanvas();
      return;
    }

    let cancelled = false;
    const img = new Image();
    img.onload = () => {
      if (cancelled) return;
      imageRef.current = img;
      appliedAiKeyRef.current = "";

      const maskCanvas = document.createElement("canvas");
      maskCanvas.width = img.naturalWidth;
      maskCanvas.height = img.naturalHeight;
      maskCanvasRef.current = maskCanvas;

      const mCtx = maskCanvas.getContext("2d", { willReadFrequently: true });
      mCtx.clearRect(0, 0, maskCanvas.width, maskCanvas.height);
      initHistory(mCtx.getImageData(0, 0, maskCanvas.width, maskCanvas.height));
      refreshTintBuffer();

      setImageDims({ width: img.naturalWidth, height: img.naturalHeight });
      recalcFitTransform(true);
    };
    img.src = imageUrl;

    return () => {
      cancelled = true;
    };
  }, [imageUrl, initHistory, recalcFitTransform, refreshTintBuffer, renderCanvas]);

  // Observe container resizes (keep zoom & pan stable while updating fit base offsets)
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver(() => {
      recalcFitTransform(false);
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [recalcFitTransform]);

  // Re-render when opacity, tool, or brush size changes
  useEffect(() => {
    renderCanvas();
  }, [renderCanvas]);

  // Merge AI auto-detect mask into native mask canvas (`#FFFFFF` -> painted stroke)
  useEffect(() => {
    const maskCanvas = maskCanvasRef.current;
    const key = aiMaskBase64 ? `${aiMaskVersion}:${aiMaskBase64}` : "";
    if (!aiMaskBase64 || !maskCanvas || appliedAiKeyRef.current === key) {
      return;
    }

    let cancelled = false;
    const aiImg = new Image();
    aiImg.onload = () => {
      if (cancelled || !maskCanvasRef.current) return;
      const targetCanvas = maskCanvasRef.current;
      const nw = targetCanvas.width;
      const nh = targetCanvas.height;

      const scratch = document.createElement("canvas");
      scratch.width = nw;
      scratch.height = nh;
      const sCtx = scratch.getContext("2d", { willReadFrequently: true });
      sCtx.drawImage(aiImg, 0, 0, nw, nh);
      const srcData = sCtx.getImageData(0, 0, nw, nh);
      const pixels = srcData.data;

      for (let i = 0; i < pixels.length; i += 4) {
        const lum = pixels[i];
        const alpha = pixels[i + 3];
        if (lum > 127 && alpha > 16) {
          pixels[i] = 255;
          pixels[i + 1] = 255;
          pixels[i + 2] = 255;
          pixels[i + 3] = 255;
        } else {
          pixels[i] = 0;
          pixels[i + 1] = 0;
          pixels[i + 2] = 0;
          pixels[i + 3] = 0;
        }
      }
      sCtx.putImageData(srcData, 0, 0);

      const mCtx = targetCanvas.getContext("2d", { willReadFrequently: true });
      mCtx.globalCompositeOperation = "source-over";
      mCtx.drawImage(scratch, 0, 0);
      pushSnapshot(mCtx.getImageData(0, 0, nw, nh));
      appliedAiKeyRef.current = key;
      refreshTintBuffer();
      renderCanvas();
    };
    aiImg.src = aiMaskBase64;

    return () => {
      cancelled = true;
    };
  }, [aiMaskBase64, aiMaskVersion, pushSnapshot, refreshTintBuffer, renderCanvas]);

  const applySnapshot = useCallback(
    (snapshot) => {
      const maskCanvas = maskCanvasRef.current;
      if (!maskCanvas || !snapshot) return;
      const mCtx = maskCanvas.getContext("2d", { willReadFrequently: true });
      mCtx.putImageData(snapshot, 0, 0);
      refreshTintBuffer();
      renderCanvas();
    },
    [refreshTintBuffer, renderCanvas]
  );

  const handleUndo = useCallback(() => {
    const snap = undoSnapshot();
    if (snap) applySnapshot(snap);
  }, [applySnapshot, undoSnapshot]);

  const handleRedo = useCallback(() => {
    const snap = redoSnapshot();
    if (snap) applySnapshot(snap);
  }, [applySnapshot, redoSnapshot]);

  const handleClearMask = useCallback(() => {
    const maskCanvas = maskCanvasRef.current;
    if (!maskCanvas) return;
    const mCtx = maskCanvas.getContext("2d", { willReadFrequently: true });
    mCtx.clearRect(0, 0, maskCanvas.width, maskCanvas.height);
    pushSnapshot(mCtx.getImageData(0, 0, maskCanvas.width, maskCanvas.height));
    appliedAiKeyRef.current = "";
    refreshTintBuffer();
    renderCanvas();
  }, [pushSnapshot, refreshTintBuffer, renderCanvas]);

  const handleSnapMaskToContent = useCallback(() => {
    const maskCanvas = maskCanvasRef.current;
    const img = imageRef.current;
    if (!maskCanvas || !img || !hasMaskRef.current) return false;

    const nw = maskCanvas.width;
    const nh = maskCanvas.height;
    const mCtx = maskCanvas.getContext("2d", { willReadFrequently: true });
    const maskImg = mCtx.getImageData(0, 0, nw, nh);
    const mData = maskImg.data;

    const tmpImgCanvas = document.createElement("canvas");
    tmpImgCanvas.width = nw;
    tmpImgCanvas.height = nh;
    const iCtx = tmpImgCanvas.getContext("2d", { willReadFrequently: true });
    iCtx.drawImage(img, 0, 0, nw, nh);
    const imgData = iCtx.getImageData(0, 0, nw, nh).data;

    let minX = nw;
    let minY = nh;
    let maxX = -1;
    let maxY = -1;
    let origCount = 0;

    for (let y = 0; y < nh; y++) {
      const rowOff = y * nw;
      for (let x = 0; x < nw; x++) {
        if (mData[(rowOff + x) * 4 + 3] > 16) {
          origCount++;
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        }
      }
    }
    if (origCount === 0 || maxX < minX) return false;

    const pad = 8;
    const rx1 = Math.max(0, minX - pad);
    const ry1 = Math.max(0, minY - pad);
    const rx2 = Math.min(nw - 1, maxX + pad);
    const ry2 = Math.min(nh - 1, maxY + pad);

    const ringR = [];
    const ringG = [];
    const ringB = [];
    for (let y = ry1; y <= ry2; y++) {
      for (let x = rx1; x <= rx2; x++) {
        const idx = (y * nw + x) * 4;
        if (mData[idx + 3] > 16) continue;
        // Kiểm tra pixel nằm trong vành đai ngoài gần nét vẽ
        let nearMask = false;
        for (let dy = -6; dy <= 6 && !nearMask; dy += 2) {
          const ny = y + dy;
          if (ny < 0 || ny >= nh) continue;
          for (let dx = -6; dx <= 6; dx += 2) {
            const nx = x + dx;
            if (nx >= 0 && nx < nw && mData[(ny * nw + nx) * 4 + 3] > 16) {
              nearMask = true;
              break;
            }
          }
        }
        if (nearMask) {
          ringR.push(imgData[idx]);
          ringG.push(imgData[idx + 1]);
          ringB.push(imgData[idx + 2]);
        }
      }
    }
    if (ringR.length < 16) return false;

    const sortedR = [...ringR].sort((a, b) => a - b);
    const sortedG = [...ringG].sort((a, b) => a - b);
    const sortedB = [...ringB].sort((a, b) => a - b);
    const mid = Math.floor(sortedR.length / 2);
    const bgR = sortedR[mid];
    const bgG = sortedG[mid];
    const bgB = sortedB[mid];

    const ringDevs = ringR.map((r, k) =>
      Math.hypot(r - bgR, ringG[k] - bgG, ringB[k] - bgB)
    );
    ringDevs.sort((a, b) => a - b);
    const bgDev85 = ringDevs[Math.min(ringDevs.length - 1, Math.floor(ringDevs.length * 0.85))];
    const threshold = Math.max(14, bgDev85 * 1.25);

    const core = new Uint8Array(nw * nh);
    for (let y = minY; y <= maxY; y++) {
      const rowOff = y * nw;
      for (let x = minX; x <= maxX; x++) {
        const p = rowOff + x;
        const idx = p * 4;
        if (mData[idx + 3] <= 16) continue;
        const dist = Math.hypot(
          imgData[idx] - bgR,
          imgData[idx + 1] - bgG,
          imgData[idx + 2] - bgB
        );
        if (dist > threshold) core[p] = 1;
      }
    }

    // Nở nhẹ lõi 3px (giao với mask gốc) để giữ toàn bộ viền răng cưa của watermark
    const refined = new Uint8Array(nw * nh);
    let refinedCount = 0;
    for (let y = minY; y <= maxY; y++) {
      const rowOff = y * nw;
      for (let x = minX; x <= maxX; x++) {
        const p = rowOff + x;
        if (mData[p * 4 + 3] <= 16) continue;
        let hit = false;
        for (let dy = -3; dy <= 3 && !hit; dy++) {
          const ny = y + dy;
          if (ny < minY || ny > maxY) continue;
          for (let dx = -3; dx <= 3; dx++) {
            const nx = x + dx;
            if (nx < minX || nx > maxX) continue;
            if (dx * dx + dy * dy <= 9 && core[ny * nw + nx] === 1) {
              hit = true;
              break;
            }
          }
        }
        if (hit) {
          refined[p] = 1;
          refinedCount++;
        }
      }
    }

    // An toàn: không thu nhỏ quá mức nếu watermark quá mờ so với nền
    if (refinedCount < Math.max(12, Math.floor(origCount * 0.1))) {
      return false;
    }

    for (let y = minY; y <= maxY; y++) {
      const rowOff = y * nw;
      for (let x = minX; x <= maxX; x++) {
        const p = rowOff + x;
        const idx = p * 4;
        if (refined[p] === 1) {
          mData[idx] = 255;
          mData[idx + 1] = 255;
          mData[idx + 2] = 255;
          mData[idx + 3] = 255;
        } else {
          mData[idx + 3] = 0;
        }
      }
    }

    mCtx.putImageData(maskImg, 0, 0);
    pushSnapshot(mCtx.getImageData(0, 0, nw, nh));
    refreshTintBuffer();
    renderCanvas();
    return true;
  }, [pushSnapshot, refreshTintBuffer, renderCanvas]);

  // Keyboard shortcuts: Ctrl+Z, Ctrl+Y / Ctrl+Shift+Z, Spacebar to pan
  useEffect(() => {
    const onKeyDown = (e) => {
      const tag = e.target?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea") return;

      if (e.code === "Space") {
        spaceHeldRef.current = true;
        renderCanvas();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) {
          handleRedo();
        } else {
          handleUndo();
        }
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
        e.preventDefault();
        handleRedo();
      }
    };

    const onKeyUp = (e) => {
      if (e.code === "Space") {
        spaceHeldRef.current = false;
        renderCanvas();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [handleRedo, handleUndo, renderCanvas]);

  const zoomAtCenter = useCallback(
    (factor) => {
      const view = viewRef.current;
      const result = zoomAroundPoint({
        prevZoom: view.zoom,
        nextZoom: view.zoom * factor,
        pivotLocalX: view.containerWidth / 2,
        pivotLocalY: view.containerHeight / 2,
        prevPanX: view.panX,
        prevPanY: view.panY,
        baseScale: view.baseScale,
        baseOffsetX: view.baseOffsetX,
        baseOffsetY: view.baseOffsetY,
      });
      view.zoom = result.zoom;
      view.panX = result.panX;
      view.panY = result.panY;
      setZoomPercent(Math.round(result.zoom * 100));
      renderCanvas();
    },
    [renderCanvas]
  );

  // Wheel zoom listener with passive: false so page never scrolls during zoom
  useEffect(() => {
    const canvas = displayCanvasRef.current;
    if (!canvas) return;

    const onWheel = (e) => {
      if (!imageRef.current) return;
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const pivotLocalX = e.clientX - rect.left;
      const pivotLocalY = e.clientY - rect.top;
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      const view = viewRef.current;

      const next = zoomAroundPoint({
        prevZoom: view.zoom,
        nextZoom: view.zoom * factor,
        pivotLocalX,
        pivotLocalY,
        prevPanX: view.panX,
        prevPanY: view.panY,
        baseScale: view.baseScale,
        baseOffsetX: view.baseOffsetX,
        baseOffsetY: view.baseOffsetY,
      });

      view.zoom = next.zoom;
      view.panX = next.panX;
      view.panY = next.panY;
      setZoomPercent(Math.round(next.zoom * 100));
      renderCanvas();
    };

    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [renderCanvas]);

  useImperativeHandle(
    ref,
    () => ({
      exportMaskBlob: async () => {
        const maskCanvas = maskCanvasRef.current;
        if (!maskCanvas || !hasMaskRef.current) return null;

        const nw = maskCanvas.width;
        const nh = maskCanvas.height;
        const mCtx = maskCanvas.getContext("2d", { willReadFrequently: true });
        const raw = mCtx.getImageData(0, 0, nw, nh);
        const src = raw.data;

        const exportCanvas = document.createElement("canvas");
        exportCanvas.width = nw;
        exportCanvas.height = nh;
        const eCtx = exportCanvas.getContext("2d");
        const outImg = eCtx.createImageData(nw, nh);
        const dst = outImg.data;

        for (let i = 0; i < src.length; i += 4) {
          const v = src[i + 3] > 16 ? 255 : 0;
          dst[i] = v;
          dst[i + 1] = v;
          dst[i + 2] = v;
          dst[i + 3] = 255;
        }
        eCtx.putImageData(outImg, 0, 0);

        return new Promise((resolve) => {
          exportCanvas.toBlob((blob) => resolve(blob), "image/png");
        });
      },
      clearMask: handleClearMask,
      snapMaskToContent: handleSnapMaskToContent,
      undo: handleUndo,
      redo: handleRedo,
      hasMask: () => hasMaskRef.current,
      resetView: () => recalcFitTransform(true),
    }),
    [handleClearMask, handleRedo, handleSnapMaskToContent, handleUndo, recalcFitTransform]
  );

  const paintSegment = useCallback(
    (fromPt, toPt, mode) => {
      const maskCanvas = maskCanvasRef.current;
      const view = viewRef.current;
      if (!maskCanvas) return;

      const mCtx = maskCanvas.getContext("2d", { willReadFrequently: true });
      const diameter = resolveImageBrushDiameter({
        brushSize,
        baseScale: view.baseScale,
      });

      mCtx.save();
      mCtx.globalCompositeOperation =
        mode === "eraser" ? "destination-out" : "source-over";
      mCtx.strokeStyle = "#ffffff";
      mCtx.fillStyle = "#ffffff";
      mCtx.lineWidth = diameter;
      mCtx.lineCap = "round";
      mCtx.lineJoin = "round";

      mCtx.beginPath();
      mCtx.moveTo(fromPt.x, fromPt.y);
      mCtx.lineTo(toPt.x, toPt.y);
      mCtx.stroke();

      if (fromPt.x === toPt.x && fromPt.y === toPt.y) {
        mCtx.beginPath();
        mCtx.arc(toPt.x, toPt.y, diameter / 2, 0, Math.PI * 2);
        mCtx.fill();
      }
      mCtx.restore();

      refreshTintBuffer();
      renderCanvas();
    },
    [brushSize, refreshTintBuffer, renderCanvas]
  );

  const handlePointerDown = (e) => {
    const canvas = displayCanvasRef.current;
    const img = imageRef.current;
    if (!canvas || !img) return;

    canvas.setPointerCapture?.(e.pointerId);
    const rect = canvas.getBoundingClientRect();
    cursorRef.current = {
      visible: true,
      localX: e.clientX - rect.left,
      localY: e.clientY - rect.top,
    };

    const shouldPan =
      tool === "pan" || spaceHeldRef.current || e.button === 1 || e.button === 2;

    if (shouldPan) {
      drawingRef.current = {
        active: true,
        mode: "pan",
        lastImgPoint: null,
        lastClientPoint: { x: e.clientX, y: e.clientY },
        strokeChanged: false,
      };
      renderCanvas();
      return;
    }

    if (e.button !== 0) return;

    const view = viewRef.current;
    const imgPt = clientToImageCoords({
      clientX: e.clientX,
      clientY: e.clientY,
      rect,
      zoom: view.zoom,
      panX: view.panX,
      panY: view.panY,
      baseScale: view.baseScale,
      baseOffsetX: view.baseOffsetX,
      baseOffsetY: view.baseOffsetY,
      naturalWidth: img.naturalWidth,
      naturalHeight: img.naturalHeight,
      clamp: true,
    });

    const strokeMode = tool === "eraser" ? "eraser" : "brush";
    drawingRef.current = {
      active: true,
      mode: strokeMode,
      lastImgPoint: imgPt,
      lastClientPoint: { x: e.clientX, y: e.clientY },
      strokeChanged: true,
    };
    paintSegment(imgPt, imgPt, strokeMode);
  };

  const handlePointerMove = (e) => {
    const canvas = displayCanvasRef.current;
    const img = imageRef.current;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    cursorRef.current = {
      visible: true,
      localX: e.clientX - rect.left,
      localY: e.clientY - rect.top,
    };

    if (!drawingRef.current.active) {
      renderCanvas();
      return;
    }

    if (drawingRef.current.mode === "pan" && drawingRef.current.lastClientPoint) {
      const dx = e.clientX - drawingRef.current.lastClientPoint.x;
      const dy = e.clientY - drawingRef.current.lastClientPoint.y;
      viewRef.current.panX += dx;
      viewRef.current.panY += dy;
      drawingRef.current.lastClientPoint = { x: e.clientX, y: e.clientY };
      renderCanvas();
      return;
    }

    if (!img || !drawingRef.current.lastImgPoint) return;

    const view = viewRef.current;
    const nextPt = clientToImageCoords({
      clientX: e.clientX,
      clientY: e.clientY,
      rect,
      zoom: view.zoom,
      panX: view.panX,
      panY: view.panY,
      baseScale: view.baseScale,
      baseOffsetX: view.baseOffsetX,
      baseOffsetY: view.baseOffsetY,
      naturalWidth: img.naturalWidth,
      naturalHeight: img.naturalHeight,
      clamp: true,
    });

    paintSegment(drawingRef.current.lastImgPoint, nextPt, drawingRef.current.mode);
    drawingRef.current.lastImgPoint = nextPt;
  };

  const finishPointerStroke = (e) => {
    const canvas = displayCanvasRef.current;
    if (canvas && e?.pointerId !== undefined) {
      try {
        canvas.releasePointerCapture?.(e.pointerId);
      } catch {
        // Ignore if pointer capture already released
      }
    }

    if (drawingRef.current.active && drawingRef.current.strokeChanged && maskCanvasRef.current) {
      const mCtx = maskCanvasRef.current.getContext("2d", { willReadFrequently: true });
      pushSnapshot(
        mCtx.getImageData(0, 0, maskCanvasRef.current.width, maskCanvasRef.current.height)
      );
    }

    drawingRef.current = {
      active: false,
      mode: null,
      lastImgPoint: null,
      lastClientPoint: null,
      strokeChanged: false,
    };
    renderCanvas();
  };

  const cursorClass =
    tool === "pan" || spaceHeldRef.current ? "cursor-grab active:cursor-grabbing" : "cursor-crosshair";

  return (
    <div
      ref={containerRef}
      className={`relative w-full h-full overflow-hidden rounded-xl border border-slate-800 checkerboard-bg select-none ${className}`}
    >
      <canvas
        ref={displayCanvasRef}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishPointerStroke}
        onPointerCancel={finishPointerStroke}
        onPointerLeave={() => {
          cursorRef.current.visible = false;
          if (!drawingRef.current.active) renderCanvas();
        }}
        onContextMenu={(e) => e.preventDefault()}
        className={`block w-full h-full touch-none ${cursorClass}`}
      />

      {imageDims.width > 0 && (
        <div className="absolute bottom-3 right-3 flex items-center gap-1.5 rounded-lg border border-slate-700/80 bg-slate-900/90 px-2.5 py-1.5 text-xs text-slate-200 shadow-lg backdrop-blur">
          <span className="hidden sm:inline text-slate-400 mr-1">
            {imageDims.width}×{imageDims.height}
          </span>
          <button
            type="button"
            onClick={() => zoomAtCenter(1 / 1.25)}
            aria-label="Thu nhỏ"
            className="rounded p-1 hover:bg-slate-800 text-slate-300"
          >
            <Minus className="w-3.5 h-3.5" />
          </button>
          <span className="min-w-[3rem] text-center font-mono">{zoomPercent}%</span>
          <button
            type="button"
            onClick={() => zoomAtCenter(1.25)}
            aria-label="Phóng to"
            className="rounded p-1 hover:bg-slate-800 text-slate-300"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => recalcFitTransform(true)}
            aria-label="Đặt lại khung nhìn"
            title="Vừa khung"
            className="rounded p-1 hover:bg-slate-800 text-slate-300"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  );
});

export default MaskCanvas;
