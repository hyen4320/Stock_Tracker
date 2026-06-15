// FastAPI 백엔드 호출 래퍼. vite proxy 덕분에 상대경로 /api 사용.

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `요청 실패 (${res.status})`);
  }
  return res.json();
}

async function postJSON(url) {
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `요청 실패 (${res.status})`);
  }
  return res.json();
}

export const api = {
  targets: () => getJSON("/api/targets"),
  modelStatus: () => getJSON("/api/model-status"),
  liveDrivers: () => getJSON("/api/live-drivers"),
  // DB에 저장된 오늘자(최신) 예측
  predict: () => getJSON("/api/predict"),
  // 과거 예측 + 실제값 이력 (적중 기록용)
  predictionsHistory: (target, limit = 60) => {
    const p = new URLSearchParams();
    if (target) p.set("target", target);
    if (limit) p.set("limit", limit);
    return getJSON(`/api/predictions/history?${p.toString()}`);
  },
  accuracy: () => getJSON("/api/accuracy"),
  history: (target, window) =>
    getJSON(`/api/history/${encodeURIComponent(target)}?window=${window}`),
  train: () => postJSON("/api/train"),
  refresh: () => postJSON("/api/refresh"),
  runPrediction: () => postJSON("/api/run-prediction"),
};
