import Icon from "../components/Icon.jsx";
import { Topbar, Timeline, HeroCard, DriverRow, LivePill } from "../components/common.jsx";
import { signPct } from "../lib/format.js";

export default function Dashboard({ targets, drivers, timeline, avgMae, onRefresh, refreshing, goDetail }) {
  const avgGap = targets.length
    ? targets.reduce((a, t) => a + t.predictedGap, 0) / targets.length
    : 0;

  return (
    <div className="screen-fade">
      <Topbar title="대시보드" sub="밤사이 변동을 반영한 내일의 예상 시초가" onRefresh={onRefresh} refreshing={refreshing}>
        <LivePill>{timeline.nowLabel}</LivePill>
      </Topbar>
      <div className="content">
        {/* 타임라인 */}
        <div className="card pad" style={{ marginBottom: 18 }}>
          <div className="card-h">
            <div>
              <div className="card-eyebrow">시간대 정렬 · 예측 파이프라인</div>
              <div className="card-title" style={{ marginTop: 4 }}>한국 마감 → 밤사이 美 SOX → 한국 시초가</div>
            </div>
            <LivePill>실시간</LivePill>
          </div>
          <Timeline timeline={timeline} />
        </div>

        {/* 예상 시초가 히어로 */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "4px 2px 12px" }}>
          <div style={{ fontSize: 15, fontWeight: 800, letterSpacing: "-0.02em", whiteSpace: "nowrap" }}>예상 시초가</div>
          <span className="chip"><Icon name="clock" size={13} /> 내일 09:00 기준</span>
        </div>
        <div className="hero-grid">
          {targets.map((tg) => (
            <HeroCard key={tg.key} t={tg} onOpen={() => goDetail(tg.key)} />
          ))}
        </div>

        {/* 드라이버 + 요약 */}
        <div className="grid" style={{ gridTemplateColumns: "1.2fr 1fr", marginTop: 18 }}>
          <div className="card pad">
            <div className="card-h" style={{ marginBottom: 6 }}>
              <div className="card-title">밤사이 드라이버</div>
              <span className="chip"><Icon name="globe" size={13} /> 미국 세션</span>
            </div>
            <DriverRow d={drivers.sox} icoName="activity" icoBg="#eef3ff" icoColor="#2f7af6" />
            <DriverRow d={drivers.fx} icoName="won" icoBg="var(--accent-soft)" icoColor="var(--accent-deep)" />
            <div className="disc" style={{ marginTop: 14 }}>
              SOX·환율의 전일 종가 대비 변동률이 모델 피처로 주입되어 예상 시초가가 실시간 갱신됩니다.
            </div>
          </div>

          <div className="card pad">
            <div className="card-title" style={{ marginBottom: 16 }}>오늘의 예측 요약</div>
            <div className="statline">
              <div className="stat">
                <div className="k">추적 종목</div>
                <div className="v num">{targets.length}</div>
              </div>
              <div className="stat">
                <div className="k">평균 예상 갭</div>
                <div className={"v num " + (avgGap >= 0 ? "up" : "down")}>{signPct(avgGap)}</div>
              </div>
              <div className="stat">
                <div className="k">모델 MAE</div>
                <div className="v num">{avgMae != null ? avgMae.toFixed(4) : "—"}</div>
              </div>
            </div>
            <div className="divider" />
            <div style={{ display: "flex", gap: 10 }}>
              <button className="btn accent" style={{ flex: 1, justifyContent: "center" }} onClick={() => goDetail(targets[0]?.key)}>
                <Icon name="candle" className="ico" /> 종목 분석 열기
              </button>
            </div>
          </div>
        </div>

        <p className="disc" style={{ marginTop: 22 }}>
          ⚠️ 본 추정치는 통계 모델의 산출물이며 투자 권유가 아닙니다. 실제 시초가는 수급·뉴스 등 다양한 요인으로 달라질 수 있습니다.
        </p>
      </div>
    </div>
  );
}
