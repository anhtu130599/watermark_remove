import React from "react";
import { Cpu, HardDriveDownload, MemoryStick, RefreshCw } from "lucide-react";

export default function HardwarePanel({
  hardware,
  health,
  selectedBackend,
  onBackendChange,
  lowMemMode,
  onLowMemModeChange,
  lastMetrics,
  onUnloadModels,
  onRefreshHardware,
  isUnloading,
}) {
  const totalRam = hardware?.total_ram_mb || 0;
  const availRam = hardware?.available_ram_mb || 0;
  const usedRam = Math.max(0, totalRam - availRam);
  const ramPct = totalRam > 0 ? Math.min(100, Math.round((usedRam / totalRam) * 100)) : 0;

  const selectableDevices = (hardware?.devices || []).filter(
    (d) => d.available && d.type !== "npu"
  );
  const npuDevice = (hardware?.devices || []).find((d) => d.type === "npu" && d.available);
  const loadedModels = health?.loaded_models || [];

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-4 space-y-3.5">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wider text-slate-300">
          <Cpu className="w-4 h-4 text-cyan-400" />
          Phần Cứng & RAM
        </h2>
        <button
          type="button"
          onClick={onRefreshHardware}
          title="Làm mới thông tin phần cứng"
          className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* CPU & NPU Info */}
      <div className="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2 text-xs space-y-1">
        <div className="font-medium text-slate-200 truncate" title={hardware?.cpu}>
          {hardware?.cpu || "Đang dò CPU..."}
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-slate-400">
          <span>Đề xuất: {hardware?.recommended_backend || "auto"}</span>
          {npuDevice && (
            <span className="rounded bg-indigo-950/70 px-1.5 py-0.5 text-indigo-300 border border-indigo-800/60">
              NPU Ready
            </span>
          )}
        </div>
      </div>

      {/* Backend selector */}
      <div>
        <label
          htmlFor="backend-select"
          className="block text-xs font-medium text-slate-400 mb-1"
        >
          Thiết bị suy luận AI
        </label>
        <select
          id="backend-select"
          value={selectedBackend}
          onChange={(e) => onBackendChange(e.target.value)}
          className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
        >
          <option value="auto">
            Tự động ({hardware?.recommended_backend || "auto"})
          </option>
          {selectableDevices.map((dev) => (
            <option key={dev.id} value={dev.id}>
              {dev.name} ({dev.id})
            </option>
          ))}
        </select>
      </div>

      {/* 16 GB Low-RAM Mode Switch */}
      <label className="flex items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 cursor-pointer">
        <div>
          <div className="text-xs font-semibold text-slate-200">
            Chế độ tiết kiệm RAM 16 GB
          </div>
          <div className="text-[11px] text-slate-400">
            Hoán đổi tuần tự Florence-2 ↔ LaMa
          </div>
        </div>
        <input
          type="checkbox"
          checked={lowMemMode}
          onChange={(e) => onLowMemModeChange(e.target.checked)}
          className="h-4 w-4 accent-cyan-400"
        />
      </label>

      {/* RAM Bar */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs">
          <span className="flex items-center gap-1 text-slate-400">
            <MemoryStick className="w-3.5 h-3.5" />
            RAM hệ thống
          </span>
          <span className="font-mono text-slate-200">
            {totalRam > 0 ? `${usedRam} / ${totalRam} MB` : "—"}
          </span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
          <div
            style={{ width: `${ramPct}%` }}
            className={`h-full transition-all ${
              ramPct > 85
                ? "bg-rose-500"
                : ramPct > 70
                ? "bg-amber-400"
                : "bg-cyan-400"
            }`}
          />
        </div>
        <div className="flex items-center justify-between text-[11px] text-slate-400">
          <span>
            Đang nạp:{" "}
            {loadedModels.length > 0 ? loadedModels.join(", ") : "Trống"}
          </span>
          <span>Trống: {availRam} MB</span>
        </div>
      </div>

      {/* Last Inference Metrics */}
      {lastMetrics && (
        <div className="grid grid-cols-3 gap-1.5 rounded-lg border border-slate-800 bg-slate-950/60 p-2 text-center text-[11px]">
          <div>
            <div className="text-slate-500">Thời gian</div>
            <div className="font-mono text-slate-200">
              {lastMetrics.latencyMs !== null ? `${Math.round(lastMetrics.latencyMs)} ms` : "—"}
            </div>
          </div>
          <div>
            <div className="text-slate-500">Backend</div>
            <div className="font-mono text-cyan-300 truncate" title={lastMetrics.backendUsed}>
              {lastMetrics.backendUsed || "—"}
            </div>
          </div>
          <div>
            <div className="text-slate-500">RSS App</div>
            <div className="font-mono text-slate-200">
              {lastMetrics.ramUsedMb ? `${lastMetrics.ramUsedMb} MB` : "—"}
            </div>
          </div>
        </div>
      )}

      {/* Unload RAM Button */}
      <button
        type="button"
        onClick={onUnloadModels}
        disabled={isUnloading || loadedModels.length === 0}
        className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700 disabled:opacity-40"
      >
        <HardDriveDownload className="w-3.5 h-3.5 text-amber-400" />
        {isUnloading ? "Đang giải phóng..." : "Giải phóng RAM AI"}
      </button>
    </div>
  );
}
