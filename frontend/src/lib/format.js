// 숫자/통화 포맷 헬퍼 (디자인 시안과 동일 규칙)
export const won = (v) => Math.round(v).toLocaleString("ko-KR");
export const signWon = (v) =>
  (v >= 0 ? "+" : "−") + Math.abs(Math.round(v)).toLocaleString("ko-KR");
export const pct = (v, d = 2) => (v * 100).toFixed(d) + "%";
export const signPct = (v, d = 2) =>
  (v >= 0 ? "+" : "−") + Math.abs(v * 100).toFixed(d) + "%";

// KST 현재 시각 라벨 (사용자 타임존과 무관하게 한국시간 표기)
export function kstNowLabel() {
  const f = new Intl.DateTimeFormat("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Seoul",
  });
  return f.format(new Date()) + " KST";
}
