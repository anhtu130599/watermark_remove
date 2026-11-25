import React, { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Sparkles } from "lucide-react";
import MaskCanvas from "./canvas/MaskCanvas";
import BeforeAfterSlider from "./components/BeforeAfterSlider";
import ControlPanel from "./components/ControlPanel";
import HardwarePanel from "./components/HardwarePanel";
import ImageUploader from "./components/ImageUploader";
import {
  detectWatermark,
  fetchHardware,
  fetchHealth,
  inpaintWatermark,
  unloadModels,
} from "./services/apiClient";

export default function App() {
  const canvasRef = useRef(null);
  const jobAbortRef = useRef(null);

  const [imageFile, setImageFile] = useState(null);
  const [imageUrl, setImageUrl] = useState("");
  const [resultUrl, setResultUrl] = useState("");
  const [viewMode, setViewMode] = useState("edit"); // 'edit' | 'compare'

  const [tool, setTool] = useState("brush");
  const [brushSize, setBrushSize] = useState(24);
  const [maskOpacity, setMaskOpacity] = useState(0.55);
  const [dilationPx, setDilationPx] = useState(3);
  const [removalMode, setRemovalMode] = useState("auto");
  const [detectPrompt, setDetectPrompt] = useState(
    "watermark, logo, text, stamp, caption"
  );

  const [aiMaskState, setAiMaskState] = useState({ dataUrl: null, version: 0 });
  const [detectBboxCount, setDetectBboxCount] = useState(null);
  const [historyState, setHistoryState] = useState({
    canUndo: false,
    canRedo: false,
    hasMask: false,
  });

  const [hardware, setHardware] = useState(null);
  const [health, setHealth] = useState(null);
  const [selectedBackend, setSelectedBackend] = useState("auto");
  const [lowMemMode, setLowMemMode] = useState(true);
  const [lastMetrics, setLastMetrics] = useState(null);

  const [isDetecting, setIsDetecting] = useState(false);
  const [isInpainting, setIsInpainting] = useState(false);
  const [isUnloading, setIsUnloading] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [statusMsg, setStatusMsg] = useState("");

  // Manage ObjectURL lifetimes strictly to avoid memory leaks
  useEffect(() => {
    return () => {
      if (imageUrl) URL.revokeObjectURL(imageUrl);
    };
  }, [imageUrl]);

  useEffect(() => {
    return () => {
      if (resultUrl) URL.revokeObjectURL(resultUrl);
    };
  }, [resultUrl]);

  const refreshSystemStatus = useCallback(async () => {
    try {
      const [hw, hl] = await Promise.all([fetchHardware(), fetchHealth()]);
      setHardware(hw);
      setHealth(hl);
    } catch (err) {
      // Backend might still be booting in dev
      console.debug("Status refresh skipped:", err?.message);
    }
  }, []);

  useEffect(() => {
    refreshSystemStatus();
  }, [refreshSystemStatus]);

  const handleImageSelect = (file) => {
    jobAbortRef.current?.abort();
    const nextUrl = URL.createObjectURL(file);
    setImageFile(file);
    setImageUrl(nextUrl);
    setResultUrl("");
    setViewMode("edit");
    setAiMaskState({ dataUrl: null, version: 0 });
    setDetectBboxCount(null);
    setErrorMsg("");
    setStatusMsg(`Đã nạp ảnh: ${file.name}`);
  };

  const handleResetImage = () => {
    jobAbortRef.current?.abort();
    setImageFile(null);
    setImageUrl("");
    setResultUrl("");
    setViewMode("edit");
    setAiMaskState({ dataUrl: null, version: 0 });
    setDetectBboxCount(null);
    setHistoryState({ canUndo: false, canRedo: false, hasMask: false });
    setErrorMsg("");
    setStatusMsg("");
  };

  const handleDetect = async () => {
    if (!imageFile) return;
    jobAbortRef.current?.abort();
    const controller = new AbortController();
    jobAbortRef.current = controller;

    setIsDetecting(true);
    setErrorMsg("");
    setStatusMsg("Florence-2 đang quét vùng watermark...");

    try {
      const res = await detectWatermark({
        imageFile,
        prompt: detectPrompt,
        dilationPx,
        backend: selectedBackend,
        signal: controller.signal,
      });

      setAiMaskState((prev) => ({
        dataUrl: res.mask_base64,
        version: prev.version + 1,
      }));
      setDetectBboxCount(res.bboxes?.length ?? 0);
      setLastMetrics({
        latencyMs: res.latency_ms ?? null,
        backendUsed: res.backend_used,
        ramUsedMb: null,
      });
      setViewMode("edit");
      setStatusMsg(
        res.bboxes?.length > 0
          ? `Đã phát hiện ${res.bboxes.length} vùng nghi ngờ watermark.`
          : "Không phát hiện watermark tự động; hãy tô mask thủ công."
      );
      await refreshSystemStatus();
    } catch (err) {
      if (err?.name !== "AbortError") {
        setErrorMsg(err?.detail || err?.message || "Lỗi nhận diện tự động.");
      }
    } finally {
      setIsDetecting(false);
    }
  };

  const handleInpaint = async () => {
    if (!imageFile || !canvasRef.current) return;
    const maskBlob = await canvasRef.current.exportMaskBlob();
    if (!maskBlob) {
      setErrorMsg("Vui lòng tô vùng watermark hoặc chạy AI dò trước khi xóa.");
      return;
    }

    jobAbortRef.current?.abort();
    const controller = new AbortController();
    jobAbortRef.current = controller;

    setIsInpainting(true);
    setErrorMsg("");
    setStatusMsg("Big-LaMa đang xóa watermark và tái tạo nền...");

    try {
      const res = await inpaintWatermark({
        imageFile,
        maskBlob,
        dilationPx,
        backend: selectedBackend,
        lowMemMode,
        mode: removalMode,
        signal: controller.signal,
      });
      const nextResultUrl = URL.createObjectURL(res.blob);
      setResultUrl(nextResultUrl);
      setLastMetrics({
        latencyMs: res.latencyMs,
        backendUsed: res.backendUsed,
        ramUsedMb: res.ramUsedMb,
      });
      setViewMode("compare");
      const usedReverseAlpha = String(res.backendUsed || "").includes("reverse-alpha");
      setStatusMsg(
        usedReverseAlpha
          ? `Khôi phục pixel gốc bằng Reverse Alpha (${res.backendUsed}).`
          : "Xử lý hoàn tất! Kéo thanh so sánh hoặc tải ảnh PNG."
      );
      await refreshSystemStatus();
    } catch (err) {
      if (err?.name !== "AbortError") {
        setErrorMsg(err?.detail || err?.message || "Lỗi khi xóa watermark.");
      }
    } finally {
      setIsInpainting(false);
    }
  };

  const handleDownload = () => {
    if (!resultUrl) return;
    const base = (imageFile?.name || "cleaned").replace(/\.[^.]+$/, "");
    const link = document.createElement("a");
    link.href = resultUrl;
    link.download = `${base}_cleaned.png`;
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  const handleUnloadModels = async () => {
    setIsUnloading(true);
    setErrorMsg("");
    try {
      const res = await unloadModels();
      setStatusMsg(
        `Đã giải phóng RAM (${res.unloaded?.length ? res.unloaded.join(", ") : "không có model"}).`
      );
      await refreshSystemStatus();
    } catch (err) {
      setErrorMsg(err?.detail || err?.message || "Không thể giải phóng RAM.");
    } finally {
      setIsUnloading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Studio Top Bar */}
      <header className="h-14 shrink-0 border-b border-slate-800/80 bg-slate-950/90 px-4 lg:px-6 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-cyan-400 to-indigo-500 text-slate-950 shadow">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-tight text-slate-100">
              AI Watermark Studio
            </h1>
            <p className="text-[11px] text-slate-400 hidden sm:block">
              Local Offline · Florence-2 + Big-LaMa
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {resultUrl && (
            <div className="inline-flex rounded-lg border border-slate-800 bg-slate-900 p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setViewMode("edit")}
                className={`rounded-md px-3 py-1 font-medium transition-colors ${
                  viewMode === "edit"
                    ? "bg-slate-800 text-cyan-300"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                Vẽ Mask
              </button>
              <button
                type="button"
                onClick={() => setViewMode("compare")}
                className={`rounded-md px-3 py-1 font-medium transition-colors ${
                  viewMode === "compare"
                    ? "bg-slate-800 text-emerald-300"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                So sánh
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Main 2-Panel Workspace */}
      <main className="flex-1 flex flex-col lg:flex-row gap-4 p-3 sm:p-4 lg:p-5 overflow-x-hidden">
        {/* Left: Interactive Viewport */}
        <section className="flex-1 min-w-0 min-h-[360px] lg:h-[calc(100vh-5.5rem)] flex flex-col gap-2">
          {(errorMsg || statusMsg) && (
            <div
              className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
                errorMsg
                  ? "border-rose-800/70 bg-rose-950/50 text-rose-200"
                  : "border-slate-800 bg-slate-900/90 text-slate-300"
              }`}
            >
              {errorMsg ? (
                <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
              ) : (
                <CheckCircle2 className="w-4 h-4 shrink-0 text-cyan-400" />
              )}
              <span className="truncate">{errorMsg || statusMsg}</span>
            </div>
          )}

          <div className="relative flex-1 min-h-[340px]">
            {!imageUrl && (
              <ImageUploader
                onImageSelect={handleImageSelect}
                onError={setErrorMsg}
              />
            )}

            {imageUrl && (
              <div
                className={`w-full h-full ${
                  viewMode === "compare" && resultUrl ? "hidden" : "block"
                }`}
              >
                <MaskCanvas
                  ref={canvasRef}
                  imageUrl={imageUrl}
                  aiMaskBase64={aiMaskState.dataUrl}
                  aiMaskVersion={aiMaskState.version}
                  tool={tool}
                  brushSize={brushSize}
                  maskOpacity={maskOpacity}
                  onHistoryChange={setHistoryState}
                />
              </div>
            )}

            {imageUrl && resultUrl && viewMode === "compare" && (
              <BeforeAfterSlider originalUrl={imageUrl} resultUrl={resultUrl} />
            )}
          </div>
        </section>

        {/* Right: Controls & Hardware Monitor */}
        <aside className="w-full min-w-0 lg:w-80 xl:w-96 shrink-0 lg:h-[calc(100vh-5.5rem)] lg:overflow-y-auto space-y-4 lg:pr-0.5">
          <ControlPanel
            hasImage={Boolean(imageUrl)}
            tool={tool}
            onToolChange={setTool}
            brushSize={brushSize}
            onBrushSizeChange={setBrushSize}
            maskOpacity={maskOpacity}
            onMaskOpacityChange={setMaskOpacity}
            dilationPx={dilationPx}
            onDilationChange={setDilationPx}
            removalMode={removalMode}
            onRemovalModeChange={setRemovalMode}
            detectPrompt={detectPrompt}
            onPromptChange={setDetectPrompt}
            historyState={historyState}
            onUndo={() => canvasRef.current?.undo()}
            onRedo={() => canvasRef.current?.redo()}
            onClearMask={() => canvasRef.current?.clearMask()}
            onSnapMask={() => {
              const ok = canvasRef.current?.snapMaskToContent();
              setStatusMsg(
                ok
                  ? "Đã co mask bám sát viền watermark (Ctrl+Z nếu muốn hoàn tác)."
                  : "Vùng tô đã khớp hoặc quá sát nền; giữ nguyên mask hiện tại."
              );
            }}
            onDetect={handleDetect}
            onInpaint={handleInpaint}
            onCancelJob={() => jobAbortRef.current?.abort()}
            onDownload={handleDownload}
            onResetImage={handleResetImage}
            viewMode={viewMode}
            onViewModeChange={setViewMode}
            hasResult={Boolean(resultUrl)}
            isDetecting={isDetecting}
            isInpainting={isInpainting}
            detectBboxCount={detectBboxCount}
          />

          <HardwarePanel
            hardware={hardware}
            health={health}
            selectedBackend={selectedBackend}
            onBackendChange={setSelectedBackend}
            lowMemMode={lowMemMode}
            onLowMemModeChange={setLowMemMode}
            lastMetrics={lastMetrics}
            onUnloadModels={handleUnloadModels}
            onRefreshHardware={refreshSystemStatus}
            isUnloading={isUnloading}
          />
        </aside>
      </main>
    </div>
  );
}
