import React, { useRef, useState } from "react";
import { Eye, MoveHorizontal } from "lucide-react";

export default function BeforeAfterSlider({ originalUrl, resultUrl }) {
  const frameRef = useRef(null);
  const [position, setPosition] = useState(50);
  const [dragging, setDragging] = useState(false);
  const [holdOriginal, setHoldOriginal] = useState(false);

  const updateFromClientX = (clientX) => {
    const el = frameRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0) return;
    const pct = ((clientX - rect.left) / rect.width) * 100;
    setPosition(Math.max(0, Math.min(100, pct)));
  };

  const effectivePct = holdOriginal ? 100 : position;

  return (
    <div className="relative flex flex-col items-center justify-center w-full h-full rounded-xl border border-slate-800 checkerboard-bg p-4 select-none overflow-hidden">
      <div
        ref={frameRef}
        role="slider"
        tabIndex={0}
        aria-label="Thanh kéo so sánh ảnh trước và sau"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(position)}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") setPosition((p) => Math.max(0, p - 2));
          if (e.key === "ArrowRight") setPosition((p) => Math.min(100, p + 2));
          if (e.key === "Home") setPosition(0);
          if (e.key === "End") setPosition(100);
        }}
        onPointerDown={(e) => {
          setDragging(true);
          e.currentTarget.setPointerCapture?.(e.pointerId);
          updateFromClientX(e.clientX);
        }}
        onPointerMove={(e) => {
          if (dragging) updateFromClientX(e.clientX);
        }}
        onPointerUp={(e) => {
          setDragging(false);
          try {
            e.currentTarget.releasePointerCapture?.(e.pointerId);
          } catch {
            // Ignore release errors
          }
        }}
        className="relative max-w-full max-h-full flex items-center justify-center cursor-ew-resize overflow-hidden rounded-lg shadow-2xl border border-slate-700/70 touch-none"
      >
        {/* Base layer: Cleaned PNG */}
        <img
          src={resultUrl}
          alt="Ảnh đã xóa watermark"
          draggable={false}
          className="block max-w-full max-h-[calc(100vh-11rem)] object-contain pointer-events-none"
        />

        {/* Overlay layer: Original image clipped cleanly at identical geometry */}
        <img
          src={originalUrl}
          alt="Ảnh gốc"
          draggable={false}
          style={{ clipPath: `inset(0 ${100 - effectivePct}% 0 0)` }}
          className="absolute inset-0 w-full h-full object-contain pointer-events-none"
        />

        {/* Divider line & handle */}
        {!holdOriginal && (
          <div
            style={{ left: `${effectivePct}%` }}
            className="absolute inset-y-0 -translate-x-1/2 w-0.5 bg-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.9)] pointer-events-none"
          >
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 flex h-9 w-9 items-center justify-center rounded-full border-2 border-cyan-300 bg-slate-950/90 text-cyan-300 shadow-lg">
              <MoveHorizontal className="w-4 h-4" />
            </div>
          </div>
        )}

        {/* Corner Badges */}
        <span className="absolute top-3 left-3 rounded-md bg-slate-950/80 px-2 py-0.5 text-[11px] font-semibold text-slate-200 border border-slate-700/70 pointer-events-none">
          Ảnh gốc
        </span>
        <span className="absolute top-3 right-3 rounded-md bg-emerald-950/80 px-2 py-0.5 text-[11px] font-semibold text-emerald-300 border border-emerald-700/70 pointer-events-none">
          Đã xóa
        </span>
      </div>

      <button
        type="button"
        onPointerDown={() => setHoldOriginal(true)}
        onPointerUp={() => setHoldOriginal(false)}
        onPointerLeave={() => setHoldOriginal(false)}
        onPointerCancel={() => setHoldOriginal(false)}
        className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900/90 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-800"
      >
        <Eye className="w-3.5 h-3.5 text-cyan-400" />
        Giữ để xem ảnh gốc
      </button>
    </div>
  );
}
