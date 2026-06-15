// SVG 데이터 시각화: 스파크라인 · 캔들 · 동조화 라인
import { useMemo } from "react";

/* ---------- 스파크라인 ---------- */
export function Sparkline({ data, color = "var(--accent)", w = 150, h = 46, fill = true, strokeW = 2 }) {
  const { line, area } = useMemo(() => {
    if (!data || data.length < 2) return { line: "", area: "" };
    const min = Math.min(...data), max = Math.max(...data);
    const rng = max - min || 1;
    const pts = data.map((v, i) => [
      (i / (data.length - 1)) * w,
      h - 4 - ((v - min) / rng) * (h - 8),
    ]);
    const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    const area = line + ` L${w} ${h} L0 ${h} Z`;
    return { line, area };
  }, [data, w, h]);
  if (!line) return null;
  const gid = "sg" + Math.round(w + h + (data[0] || 0));
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block" }}>
      {fill && (
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={color} stopOpacity="0.22" />
            <stop offset="1" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
      )}
      {fill && <path d={area} fill={`url(#${gid})`} />}
      <path d={line} fill="none" stroke={color} strokeWidth={strokeW} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/* ---------- 캔들 차트 (상승=빨강 / 하락=파랑) ---------- */
export function CandleChart({ ohlc, height = 360 }) {
  const W = 1000, H = height, padL = 4, padR = 56, padT = 12, padB = 24;
  const { dates, open, high, low, close } = ohlc;
  const n = dates.length;
  if (!n) return null;
  const all = high.concat(low).filter((v) => v != null && !Number.isNaN(v));
  const min = Math.min(...all), max = Math.max(...all);
  const rng = max - min || 1;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const x = (i) => padL + (i / Math.max(1, n - 1)) * plotW;
  const y = (v) => padT + (1 - (v - min) / rng) * plotH;
  const cw = Math.max(2, (plotW / n) * 0.62);
  const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => min + f * rng);
  const fmt = (v) => Math.round(v).toLocaleString("ko-KR");
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: "block" }} preserveAspectRatio="none">
      {grid.map((g, i) => (
        <g key={i}>
          <line x1={padL} x2={W - padR} y1={y(g)} y2={y(g)} stroke="var(--border)" strokeWidth="1" />
          <text x={W - padR + 8} y={y(g) + 4} fontSize="13" fill="var(--text-3)" className="num">{fmt(g)}</text>
        </g>
      ))}
      {dates.map((d, i) => {
        if (close[i] == null || open[i] == null) return null;
        const up = close[i] >= open[i];
        const c = up ? "var(--up)" : "var(--down)";
        const oY = y(open[i]), cY = y(close[i]);
        const bodyTop = Math.min(oY, cY), bodyH = Math.max(1.5, Math.abs(cY - oY));
        return (
          <g key={i}>
            <line x1={x(i)} x2={x(i)} y1={y(high[i])} y2={y(low[i])} stroke={c} strokeWidth="1.2" />
            <rect x={x(i) - cw / 2} y={bodyTop} width={cw} height={bodyH} fill={c} rx="0.8" />
          </g>
        );
      })}
    </svg>
  );
}

/* ---------- 동조화 라인 차트 (다중 시리즈, 기준=100 정규화) ---------- */
export function SyncChart({ seriesA, seriesB, colorA = "var(--accent)", colorB = "#22b8cf", height = 300 }) {
  const W = 1000, H = height, padL = 4, padR = 52, padT = 14, padB = 24;
  const clean = (s) => (s || []).filter((v) => v != null && !Number.isNaN(v));
  const all = clean(seriesA).concat(clean(seriesB));
  if (!all.length) return null;
  const min = Math.min(...all), max = Math.max(...all);
  const rng = max - min || 1;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const n = Math.max(seriesA.length, seriesB.length);
  const x = (i) => padL + (i / Math.max(1, n - 1)) * plotW;
  const y = (v) => padT + (1 - (v - min) / rng) * plotH;
  // null 구간은 끊고, 유효 구간만 폴리라인으로 연결
  const path = (s) => {
    let d = "", penDown = false;
    (s || []).forEach((v, i) => {
      if (v == null || Number.isNaN(v)) { penDown = false; return; }
      d += (penDown ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1) + " ";
      penDown = true;
    });
    return d.trim();
  };
  const grid = [0, 0.5, 1].map((f) => min + f * rng);
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: "block" }} preserveAspectRatio="none">
      {grid.map((g, i) => (
        <g key={i}>
          <line x1={padL} x2={W - padR} y1={y(g)} y2={y(g)} stroke="var(--border)" strokeWidth="1" />
          <text x={W - padR + 8} y={y(g) + 4} fontSize="13" fill="var(--text-3)" className="num">{g.toFixed(0)}</text>
        </g>
      ))}
      <path d={path(seriesB)} fill="none" stroke={colorB} strokeWidth="2.4" strokeLinejoin="round" opacity="0.9" />
      <path d={path(seriesA)} fill="none" stroke={colorA} strokeWidth="2.4" strokeLinejoin="round" />
    </svg>
  );
}
