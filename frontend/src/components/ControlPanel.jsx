import React from "react";
import {
  Brush,
  Crosshair,
  Download,
  Eraser,
  FolderOpen,
  Hand,
  Loader2,
  Redo2,
  ScanSearch,
  SplitSquareHorizontal,
  Trash2,
  Undo2,
  Wand2,
  XCircle,
} from "lucide-react";

export default function ControlPanel({
  hasImage,
  tool,
  onToolChange,
  brushSize,
  onBrushSizeChange,
  maskOpacity,
  onMaskOpacityChange,
  dilationPx,
  onDilationChange,
  removalMode = "auto",
  onRemovalModeChange,
  detectPrompt,
  onPromptChange,
  historyState,
  onUndo,
  onRedo,
  onClearMask,
  onSnapMask,
  onDetect,
  onInpaint,
  onCancelJob,
  onDownload,
  onResetImage,
  viewMode,
  onViewModeChange,
  hasResult,
  isDetecting,
  isInpainting,
  detectBboxCount,
}) {
  const isBusy = isDetecting || isInpainting;

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          Bảng Điều Khiển
        </h2>
        {hasImage && (
          <button
            type="button"
            onClick={onResetImage}
            disabled={isBusy}
            className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2.5 py-1 text-xs font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-50"
          >
            <FolderOpen className="w-3.5 h-3.5" />
            Đổi ảnh khác
          </button>
        )}
      </div>

      {/* Tool Selector */}
      <div>
        <span className="block text-xs font-medium text-slate-400 mb-2">
          Công cụ vẽ Mask
        </span>
        <div className="grid grid-cols-3 gap-1.5 sm:gap-2">
          {[
            { id: "brush", label: "Cọ vẽ", icon: Brush },
            { id: "eraser", label: "Tẩy", icon: Eraser },
            { id: "pan", label: "Kéo khung", icon: Hand },
          ].map(({ id, label, icon: Icon }) => {
            const active = tool === id;
            return (
              <button
                key={id}
                type="button"
                disabled={!hasImage || isBusy}
                onClick={() => onToolChange(id)}
                className={`flex items-center justify-center gap-1 rounded-lg border px-1.5 sm:px-2.5 py-2 text-[11px] sm:text-xs font-semibold transition-colors ${
                  active
                    ? "border-cyan-400 bg-cyan-500/20 text-cyan-300"
                    : "border-slate-700/80 bg-slate-800/60 text-slate-300 hover:bg-slate-800"
                } disabled:opacity-40`}
              >
                <Icon className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate">{label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* History Actions */}
      <div className="grid grid-cols-3 gap-1.5 sm:gap-2">
        <button
          type="button"
          onClick={onUndo}
          disabled={!hasImage || !historyState.canUndo || isBusy}
          className="inline-flex items-center justify-center gap-1 rounded-lg border border-slate-700/80 bg-slate-800/70 px-1.5 sm:px-2 py-1.5 text-[11px] sm:text-xs font-medium text-slate-200 hover:bg-slate-700 disabled:opacity-40"
        >
          <Undo2 className="w-3.5 h-3.5 shrink-0" />
          <span className="truncate">Hoàn tác</span>
        </button>
        <button
          type="button"
          onClick={onRedo}
          disabled={!hasImage || !historyState.canRedo || isBusy}
          className="inline-flex items-center justify-center gap-1 rounded-lg border border-slate-700/80 bg-slate-800/70 px-1.5 sm:px-2 py-1.5 text-[11px] sm:text-xs font-medium text-slate-200 hover:bg-slate-700 disabled:opacity-40"
        >
          <Redo2 className="w-3.5 h-3.5 shrink-0" />
          <span className="truncate">Làm lại</span>
        </button>
        <button
          type="button"
          onClick={onClearMask}
          disabled={!hasImage || !historyState.hasMask || isBusy}
          className="inline-flex items-center justify-center gap-1 rounded-lg border border-rose-900/60 bg-rose-950/30 px-1.5 sm:px-2 py-1.5 text-[11px] sm:text-xs font-medium text-rose-300 hover:bg-rose-900/40 disabled:opacity-40"
        >
          <Trash2 className="w-3.5 h-3.5 shrink-0" />
          <span className="truncate">Xóa mask</span>
        </button>
      </div>

      {onSnapMask && (
        <button
          type="button"
          onClick={onSnapMask}
          disabled={!hasImage || !historyState.hasMask || isBusy}
          title="Thu gọn vùng tô thô để bám sát chữ/logo watermark, tránh xóa nhầm đường nét nền xung quanh"
          className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg border border-cyan-700/50 bg-cyan-950/30 px-3 py-1.5 text-xs font-medium text-cyan-200 hover:bg-cyan-900/40 disabled:opacity-40 transition-colors"
        >
          <Crosshair className="w-3.5 h-3.5 shrink-0" />
          <span>Co sát nét watermark</span>
        </button>
      )}

      {/* Sliders */}
      <div className="space-y-3 pt-1">
        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-slate-400">Cỡ cọ</span>
            <span className="font-mono text-slate-200">{brushSize} px</span>
          </div>
          <input
            type="range"
            min={5}
            max={150}
            value={brushSize}
            disabled={!hasImage}
            onChange={(e) => onBrushSizeChange(Number(e.target.value))}
            className="w-full accent-cyan-400"
          />
        </div>

        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-slate-400">Độ mờ lớp Mask</span>
            <span className="font-mono text-slate-200">
              {Math.round(maskOpacity * 100)}%
            </span>
          </div>
          <input
            type="range"
            min={20}
            max={90}
            value={Math.round(maskOpacity * 100)}
            disabled={!hasImage}
            onChange={(e) => onMaskOpacityChange(Number(e.target.value) / 100)}
            className="w-full accent-rose-400"
          />
        </div>

        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-slate-400">Nở viền mask (Dilation)</span>
            <span className="font-mono text-slate-200">{dilationPx} px</span>
          </div>
          <input
            type="range"
            min={0}
            max={25}
            value={dilationPx}
            disabled={!hasImage}
            onChange={(e) => onDilationChange(Number(e.target.value))}
            className="w-full accent-amber-400"
          />
        </div>
      </div>

      {/* Florence-2 Auto-Detect */}
      <div className="border-t border-slate-800 pt-3 space-y-2">
        <div className="flex items-center justify-between">
          <label
            htmlFor="florence-prompt"
            className="text-xs font-medium text-slate-300"
          >
            Prompt dò tự động (Florence-2)
          </label>
          {detectBboxCount !== null && (
            <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-cyan-300">
              {detectBboxCount} vùng
            </span>
          )}
        </div>
        <input
          id="florence-prompt"
          type="text"
          value={detectPrompt}
          disabled={!hasImage || isBusy}
          onChange={(e) => onPromptChange(e.target.value)}
          placeholder="watermark, logo, text, stamp, caption"
          className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-100 placeholder:text-slate-500 focus:border-cyan-400 focus:outline-none disabled:opacity-50"
        />
        <button
          type="button"
          onClick={onDetect}
          disabled={!hasImage || isBusy}
          className="w-full inline-flex items-center justify-center gap-2 rounded-lg border border-indigo-500/50 bg-indigo-500/15 px-3 py-2 text-xs font-semibold text-indigo-200 hover:bg-indigo-500/25 disabled:opacity-40 transition-colors"
        >
          {isDetecting ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <ScanSearch className="w-4 h-4" />
          )}
          {isDetecting ? "Đang dò watermark..." : "Tự động dò (AI)"}
        </button>
      </div>

      {/* Primary Inpaint Action & Export */}
      <div className="border-t border-slate-800 pt-3 space-y-2.5">
        {onRemovalModeChange && (
          <div>
            <label
              htmlFor="removal-mode-select"
              className="block text-xs font-medium text-slate-400 mb-1"
            >
              Chế độ khử Watermark
            </label>
            <select
              id="removal-mode-select"
              value={removalMode}
              disabled={!hasImage || isBusy}
              onChange={(e) => onRemovalModeChange(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none disabled:opacity-50"
            >
              <option value="auto">Tự động (Reverse Alpha + AI)</option>
              <option value="reverse_alpha">Khử Alpha bán trong suốt (Giữ nét gốc)</option>
              <option value="inpaint">Tái tạo AI + Ghép vân (Che đặc)</option>
            </select>
          </div>
        )}
        {!isBusy ? (
          <button
            type="button"
            onClick={onInpaint}
            disabled={!hasImage || !historyState.hasMask}
            className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-cyan-500 to-teal-400 px-4 py-2.5 text-sm font-bold text-slate-950 hover:from-cyan-400 hover:to-teal-300 disabled:opacity-40 transition-all shadow-md"
          >
            <Wand2 className="w-4 h-4" />
            Xóa Watermark (LaMa)
          </button>
        ) : (
          <button
            type="button"
            onClick={onCancelJob}
            className="w-full inline-flex items-center justify-center gap-2 rounded-lg border border-rose-500/60 bg-rose-500/20 px-4 py-2.5 text-sm font-semibold text-rose-200 hover:bg-rose-500/30"
          >
            <XCircle className="w-4 h-4" />
            Hủy tác vụ đang chạy
          </button>
        )}

        {hasResult && (
          <div className="grid grid-cols-2 gap-2 pt-1">
            <button
              type="button"
              onClick={() =>
                onViewModeChange(viewMode === "compare" ? "edit" : "compare")
              }
              className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-700"
            >
              <SplitSquareHorizontal className="w-3.5 h-3.5" />
              {viewMode === "compare" ? "Sửa tiếp Mask" : "So sánh Trước/Sau"}
            </button>
            <button
              type="button"
              onClick={onDownload}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-2 text-xs font-bold text-slate-950 hover:bg-emerald-400"
            >
              <Download className="w-3.5 h-3.5" />
              Tải ảnh PNG
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
