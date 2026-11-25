import React, { useEffect, useRef, useState } from "react";
import { ImagePlus, Sparkles, Upload } from "lucide-react";

const ALLOWED_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const MAX_BYTES = 20 * 1024 * 1024;

function createSyntheticSampleFile() {
  return new Promise((resolve) => {
    const canvas = document.createElement("canvas");
    canvas.width = 1280;
    canvas.height = 720;
    const ctx = canvas.getContext("2d");

    const grad = ctx.createLinearGradient(0, 0, 1280, 720);
    grad.addColorStop(0, "#0f172a");
    grad.addColorStop(0.5, "#134e4a");
    grad.addColorStop(1, "#1e293b");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 1280, 720);

    // Subtle geometric landscape shapes
    ctx.fillStyle = "rgba(56, 189, 248, 0.16)";
    ctx.beginPath();
    ctx.arc(960, 200, 130, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "rgba(15, 23, 42, 0.45)";
    ctx.beginPath();
    ctx.moveTo(0, 620);
    ctx.lineTo(420, 360);
    ctx.lineTo(840, 560);
    ctx.lineTo(1280, 320);
    ctx.lineTo(1280, 720);
    ctx.lineTo(0, 720);
    ctx.closePath();
    ctx.fill();

    // Clear watermark stamps to test AI detect & LaMa inpainting
    ctx.save();
    ctx.translate(640, 360);
    ctx.rotate(-0.28);
    ctx.font = "bold 56px Inter, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillStyle = "rgba(255, 255, 255, 0.62)";
    ctx.fillText("SAMPLE WATERMARK 2026", 0, 0);
    ctx.restore();

    ctx.font = "bold 28px Inter, system-ui, sans-serif";
    ctx.fillStyle = "rgba(248, 250, 252, 0.78)";
    ctx.fillText("STOCK PHOTO PREVIEW", 48, 668);

    canvas.toBlob((blob) => {
      const file = new File([blob], "sample_watermarked.png", { type: "image/png" });
      resolve(file);
    }, "image/png");
  });
}

export default function ImageUploader({ onImageSelect, onError }) {
  const inputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);

  const validateAndEmit = (file) => {
    if (!file) return;
    if (!ALLOWED_TYPES.has(file.type)) {
      onError?.("Định dạng không hỗ trợ. Chỉ chấp nhận JPEG, PNG hoặc WebP.");
      return;
    }
    if (file.size > MAX_BYTES) {
      onError?.("Dung lượng ảnh vượt quá giới hạn 20 MB.");
      return;
    }
    onError?.("");
    onImageSelect?.(file);
  };

  useEffect(() => {
    const onPaste = (e) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const item of items) {
        if (item.type.startsWith("image/")) {
          const pasted = item.getAsFile();
          if (pasted) {
            validateAndEmit(pasted);
            break;
          }
        }
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  });

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer?.files?.[0];
    if (file) validateAndEmit(file);
  };

  const handleLoadSample = async () => {
    const sample = await createSyntheticSampleFile();
    validateAndEmit(sample);
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      className={`flex flex-col items-center justify-center w-full h-full min-h-[340px] rounded-xl border-2 border-dashed p-5 sm:p-8 text-center transition-colors ${
        isDragging
          ? "border-cyan-400 bg-cyan-950/20"
          : "border-slate-700/80 bg-slate-900/50 hover:border-slate-500"
      }`}
    >
      <div className="mb-4 rounded-2xl bg-slate-800/80 p-4 text-cyan-400 shadow-inner">
        <ImagePlus className="w-10 h-10" />
      </div>

      <h2 className="text-lg font-semibold text-slate-100">
        Tải ảnh cần xóa watermark
      </h2>
      <p className="mt-1.5 max-w-md text-sm text-slate-400">
        Kéo thả tệp vào đây, bấm chọn tệp hoặc dán trực tiếp bằng{" "}
        <kbd className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-200">
          Ctrl+V
        </kbd>
        . Hỗ trợ JPG, PNG, WebP (tối đa 20 MB).
      </p>

      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) validateAndEmit(file);
          e.target.value = "";
        }}
        className="hidden"
      />

      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="inline-flex items-center gap-2 rounded-lg bg-cyan-500 px-4 py-2.5 text-sm font-semibold text-slate-950 hover:bg-cyan-400 transition-colors"
        >
          <Upload className="w-4 h-4" />
          Chọn ảnh từ máy
        </button>

        <button
          type="button"
          onClick={handleLoadSample}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-4 py-2.5 text-sm font-medium text-slate-200 hover:bg-slate-700 transition-colors"
        >
          <Sparkles className="w-4 h-4 text-amber-400" />
          Thử ảnh mẫu có Watermark
        </button>
      </div>
    </div>
  );
}
