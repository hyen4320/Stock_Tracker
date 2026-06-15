// Feather 스타일 단일 스트로크 아이콘
const PATHS = {
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM13 13h7v7h-7zM4 13h7v7H4z",
  candle: "M5 3v4M5 17v4M5 7h0M19 3v6M19 15v6M12 5v3M12 16v3",
  sliders: "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6",
  cpu: "M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3M6 6h12v12H6z M9 9h6v6H9z",
  refresh: "M23 4v6h-6M1 20v-6h6M3.5 9a9 9 0 0114.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0020.5 15",
  brain: "M12 5a3 3 0 00-5.6-1.5A3 3 0 003 6a3 3 0 00.5 5A3 3 0 008 16a3 3 0 004 1 3 3 0 004-1 3 3 0 004.5-5 3 3 0 00.5-5 3 3 0 00-3.4-2.5A3 3 0 0012 5z",
  clock: "M12 7v5l3 2M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  bell: "M18 8a6 6 0 00-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 01-3.4 0",
  arrowUp: "M12 19V5M5 12l7-7 7 7",
  arrowDown: "M12 5v14M19 12l-7 7-7-7",
  trend: "M23 6l-9.5 9.5-5-5L1 18M17 6h6v6",
  chevron: "M9 18l6-6-6-6",
  dot: "M12 12h.01",
  activity: "M22 12h-4l-3 9L9 3l-3 9H2",
  globe: "M12 21a9 9 0 100-18 9 9 0 000 18zM3 12h18M12 3c2.5 2.7 3.8 5.8 4 9-.2 3.2-1.5 6.3-4 9-2.5-2.7-3.8-5.8-4-9 .2-3.2 1.5-6.3 4-9z",
  won: "M4 6l3 9 3-7 3 7 3-9M3 11h18M3 14h18",
  check: "M20 6L9 17l-5-5",
  info: "M12 16v-4M12 8h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  layers: "M12 2l9 5-9 5-9-5 9-5zM3 12l9 5 9-5M3 17l9 5 9-5",
  spark: "M12 2l2.4 7.4H22l-6 4.6 2.3 7.4-6.3-4.6L5.7 21.4 8 14 2 9.4h7.6z",
  target: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 16a4 4 0 100-8 4 4 0 000 8zM12 13a1 1 0 100-2 1 1 0 000 2z",
  shield: "M12 2l8 3v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V5l8-3z",
  lock: "M6 11h12v9H6zM8 11V7a4 4 0 018 0v4",
  logout: "M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9",
  close: "M18 6L6 18M6 6l12 12",
  back: "M9 11l-4 4 4 4M5 15h11a4 4 0 000-8H9",
  history: "M3 3v5h5M3.05 13a9 9 0 1 0 2.5-6.4L3 8M12 7v5l4 2",
};

export default function Icon({ name, className, style, size = 19 }) {
  const p = PATHS[name] || "M12 12h.01";
  const filled = name === "dot";
  return (
    <svg
      className={className}
      style={style}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={p} />
    </svg>
  );
}
