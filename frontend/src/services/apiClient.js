export class ApiError extends Error {
  constructor(detail, { status = 500, code = "INTERNAL_ERROR" } = {}) {
    super(detail || "Lỗi kết nối máy chủ.");
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail || "Lỗi kết nối máy chủ.";
  }
}

async function parseErrorResponse(res) {
  let detail = `Lỗi HTTP ${res.status}`;
  let code = "HTTP_ERROR";
  try {
    const data = await res.json();
    if (data?.detail) detail = String(data.detail);
    if (data?.code) code = String(data.code);
  } catch {
    try {
      const txt = await res.text();
      if (txt) detail = txt.slice(0, 240);
    } catch {
      // Ignore fallback read failure
    }
  }
  return new ApiError(detail, { status: res.status, code });
}

export async function fetchHealth({ signal } = {}) {
  const res = await fetch("/api/v1/health", { signal });
  if (!res.ok) throw await parseErrorResponse(res);
  return res.json();
}

export async function fetchHardware({ signal } = {}) {
  const res = await fetch("/api/v1/hardware", { signal });
  if (!res.ok) throw await parseErrorResponse(res);
  return res.json();
}

export async function detectWatermark({
  imageFile,
  prompt,
  dilationPx = 5,
  backend = "auto",
  signal,
}) {
  const form = new FormData();
  form.append("image", imageFile);
  if (prompt && prompt.trim()) {
    form.append("prompt", prompt.trim());
  }
  form.append("dilation_px", String(dilationPx));
  form.append("backend", backend || "auto");

  const res = await fetch("/api/v1/detect", {
    method: "POST",
    body: form,
    signal,
  });
  if (!res.ok) throw await parseErrorResponse(res);
  return res.json();
}

export async function inpaintWatermark({
  imageFile,
  maskBlob,
  dilationPx = 5,
  backend = "auto",
  lowMemMode = true,
  mode = "auto",
  signal,
}) {
  const form = new FormData();
  form.append("image", imageFile);
  form.append("mask", maskBlob, "mask.png");
  form.append("dilation_px", String(dilationPx));
  form.append("backend", backend || "auto");
  form.append("low_mem_mode", String(Boolean(lowMemMode)));
  form.append("mode", mode || "auto");

  const res = await fetch("/api/v1/inpaint", {
    method: "POST",
    body: form,
    signal,
  });
  if (!res.ok) throw await parseErrorResponse(res);

  const blob = await res.blob();
  const latencyHeader = res.headers.get("X-Latency-Ms");
  const backendUsed = res.headers.get("X-Backend-Used") || backend || "auto";
  const ramHeader = res.headers.get("X-Ram-Used-MB");

  return {
    blob,
    latencyMs: latencyHeader ? Number(latencyHeader) : null,
    backendUsed,
    ramUsedMb: ramHeader ? Number(ramHeader) : null,
  };
}

export async function unloadModels({ signal } = {}) {
  const res = await fetch("/api/v1/models/unload", {
    method: "POST",
    signal,
  });
  if (!res.ok) throw await parseErrorResponse(res);
  return res.json();
}
