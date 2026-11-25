import { useCallback, useRef, useState } from "react";

const DEFAULT_MAX_SNAPSHOTS = 20;

export function scanHasMask(imageData) {
  if (!imageData?.data) return false;
  const data = imageData.data;
  for (let i = 3; i < data.length; i += 4) {
    if (data[i] > 16) {
      return true;
    }
  }
  return false;
}

/**
 * Bounded Undo/Redo snapshot stack for the native-resolution offscreen mask canvas.
 */
export function useCanvasHistory(maxSnapshots = DEFAULT_MAX_SNAPSHOTS) {
  const stackRef = useRef([]);
  const indexRef = useRef(-1);
  const [meta, setMeta] = useState({
    canUndo: false,
    canRedo: false,
    hasMask: false,
  });

  const syncMeta = useCallback(() => {
    const stack = stackRef.current;
    const idx = indexRef.current;
    const current = idx >= 0 ? stack[idx] : null;
    const next = {
      canUndo: idx > 0,
      canRedo: idx >= 0 && idx < stack.length - 1,
      hasMask: scanHasMask(current),
    };
    setMeta(next);
    return next;
  }, []);

  const initHistory = useCallback(
    (initialImageData) => {
      stackRef.current = initialImageData ? [initialImageData] : [];
      indexRef.current = initialImageData ? 0 : -1;
      return syncMeta();
    },
    [syncMeta]
  );

  const pushSnapshot = useCallback(
    (imageData) => {
      if (!imageData) return meta;
      const truncated = stackRef.current.slice(0, indexRef.current + 1);
      truncated.push(imageData);
      if (truncated.length > maxSnapshots) {
        truncated.shift();
      }
      stackRef.current = truncated;
      indexRef.current = truncated.length - 1;
      return syncMeta();
    },
    [maxSnapshots, meta, syncMeta]
  );

  const undoSnapshot = useCallback(() => {
    if (indexRef.current <= 0) return null;
    indexRef.current -= 1;
    const snapshot = stackRef.current[indexRef.current] ?? null;
    syncMeta();
    return snapshot;
  }, [syncMeta]);

  const redoSnapshot = useCallback(() => {
    if (indexRef.current < 0 || indexRef.current >= stackRef.current.length - 1) {
      return null;
    }
    indexRef.current += 1;
    const snapshot = stackRef.current[indexRef.current] ?? null;
    syncMeta();
    return snapshot;
  }, [syncMeta]);

  return {
    ...meta,
    initHistory,
    pushSnapshot,
    undoSnapshot,
    redoSnapshot,
  };
}
