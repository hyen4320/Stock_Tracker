// 종목별 표시 메타데이터 + 모델 민감도(β)·기여도.
//
// ticker/logo/색상은 표시용 상수다. sens(β)·contrib·ci 는 학습된 모델의
// 평균 반응도를 나타내는 "예시 계수"로, 현재 백엔드 API가 노출하지 않아
// 시안 값을 사용한다. 추후 /api/predict 가 종목별 β·기여도를 반환하면
// 그 값으로 교체하면 된다.
export const TARGET_META = {
  삼성전자: {
    ticker: "005930.KS",
    logo: "S",
    logoBg: "#1428a0",
    color: "#1f6feb",
    ci: 0.0048, // ±0.48%p 예측 신뢰구간
    sens: { base: 0.0019, betaSox: 0.335, betaFx: 0.353 },
    contrib: [
      { name: "SOX 수익률", v: 0.61 },
      { name: "원/달러 수익률", v: 0.12 },
      { name: "5일 모멘텀", v: 0.08 },
      { name: "20일 모멘텀", v: 0.05 },
      { name: "잔차/기타", v: 0.06 },
    ],
  },
  SK하이닉스: {
    ticker: "000660.KS",
    logo: "SK",
    logoBg: "#e0524a",
    color: "#e0524a",
    ci: 0.0061,
    sens: { base: 0.0027, betaSox: 0.56, betaFx: 0.5 },
    contrib: [
      { name: "SOX 수익률", v: 1.02 },
      { name: "원/달러 수익률", v: 0.17 },
      { name: "5일 모멘텀", v: 0.14 },
      { name: "20일 모멘텀", v: 0.07 },
      { name: "잔차/기타", v: 0.06 },
    ],
  },
};

const PALETTE = ["#1428a0", "#e0524a", "#6366f1", "#0ea5e9", "#16a34a"];

export function metaFor(name, idx = 0) {
  if (TARGET_META[name]) return TARGET_META[name];
  // 알려지지 않은 종목: 머리글자 + 팔레트로 기본값 생성
  const logo = name.slice(0, 2).toUpperCase();
  const bg = PALETTE[idx % PALETTE.length];
  return {
    ticker: "",
    logo,
    logoBg: bg,
    color: bg,
    ci: 0.005,
    sens: { base: 0.002, betaSox: 0.4, betaFx: 0.4 },
    contrib: [],
  };
}
