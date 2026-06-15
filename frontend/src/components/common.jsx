// 공용 UI 컴포넌트: 펄스 · 라이브칩 · 상단바 · 타임라인 · 히어로 · 드라이버
import Icon from "./Icon.jsx";
import { Sparkline } from "./Charts.jsx";
import { won, signWon, signPct } from "../lib/format.js";

/* ---------- 라이브 펄스 ---------- */
export function Pulse() {
  return <span className="pulse-dot"><i /></span>;
}
export function LivePill({ children = "LIVE" }) {
  return <span className="live-pill"><Pulse />{children}</span>;
}

/* ---------- 상단바 ---------- */
export function Topbar({ title, sub, onRefresh, refreshing, children }) {
  return (
    <div className="topbar">
      <div>
        <h1>{title}</h1>
        <div className="sub">{sub}</div>
      </div>
      <div className="top-actions">
        {children}
        {onRefresh && (
          <button className="btn" onClick={onRefresh} disabled={refreshing}>
            <Icon name="refresh" className="ico" style={refreshing ? { animation: "spin 1s linear infinite" } : null} />
            {refreshing ? "갱신 중…" : "새로고침"}
          </button>
        )}
      </div>
    </div>
  );
}

/* ---------- 시간대 타임라인 ---------- */
export function Timeline({ timeline }) {
  const { nodes, progress } = timeline;
  return (
    <div className="timeline">
      <div className="tl-line"><div className="tl-fill" style={{ width: progress * 100 + "%" }} /></div>
      {nodes.map((nd, i) => (
        <div className="tl-node" key={i}>
          <div className={"tl-dot " + (nd.state === "done" ? "done" : nd.state === "live" ? "live" : "")}>
            {nd.state === "done" ? <Icon name="check" size={15} />
              : nd.state === "live" ? <Pulse />
              : <Icon name="target" size={14} style={{ color: "var(--text-3)" }} />}
          </div>
          <div className="tl-t">{nd.t}</div>
          <div className="tl-d">{nd.d}</div>
          {nd.state === "live"
            ? <div className="tl-now"><span className="up">{nd.price}</span></div>
            : <div className="tl-now" style={{ color: "var(--text-3)" }}>{nd.price}</div>}
        </div>
      ))}
    </div>
  );
}

/* ---------- 예상 시초가 히어로 카드 ---------- */
export function HeroCard({ t, onOpen, showCI = true }) {
  const up = t.predictedGap >= 0;
  const dir = up ? "up" : "down";
  const spark = (t.spark || []).slice(-30);
  const lo = t.predictedGap - t.ci, hi = t.predictedGap + t.ci;
  const span = Math.max(Math.abs(lo), Math.abs(hi)) * 1.25 || 0.01;
  const toPctPos = (v) => 50 + (v / (span * 2)) * 100;
  return (
    <div className="hero-card" onClick={onOpen}>
      <div className="hero-top">
        <div>
          <div className="hero-name">{t.key}</div>
          <div className="hero-ticker mono">{t.ticker}</div>
        </div>
        <div className="hero-logo" style={{ background: t.logoBg }}>{t.logo}</div>
      </div>

      <div className="hero-est-label">예상 시초가 · 내일 09:00</div>
      <div className={"hero-est num " + dir}>
        {won(t.estimatedOpen)}<span className="won">원</span>
      </div>

      <div className={"hero-delta " + dir}>
        <Icon name={up ? "arrowUp" : "arrowDown"} size={15} />
        {signWon(t.change)}원 · {signPct(t.predictedGap)}
      </div>

      {showCI && (
        <div className="ci-wrap">
          <div className="ci-track">
            <div className="ci-band" style={{
              left: toPctPos(lo) + "%", right: 100 - toPctPos(hi) + "%",
              background: up ? "var(--up-soft)" : "var(--down-soft)",
            }} />
            <div className="ci-mark" style={{ left: toPctPos(t.predictedGap) + "%", background: up ? "var(--up)" : "var(--down)" }} />
          </div>
          <div className="ci-labels">
            <span>{signPct(lo)}</span>
            <span>예측구간 95%</span>
            <span>{signPct(hi)}</span>
          </div>
        </div>
      )}

      <div className="hero-close">전일 종가 <span className="num" style={{ color: "var(--text-2)", fontWeight: 700 }}>{won(t.lastClose)}원</span></div>
      {spark.length > 1 && (
        <div className="hero-spark">
          <Sparkline data={spark} color={up ? "var(--up)" : "var(--down)"} w={160} h={56} />
        </div>
      )}
    </div>
  );
}

/* ---------- 드라이버 행 ---------- */
export function DriverRow({ d, icoName, icoBg, icoColor }) {
  const up = d.ret >= 0;
  return (
    <div className="driver-row">
      <div className="driver-ico" style={{ background: icoBg, color: icoColor }}><Icon name={icoName} size={20} /></div>
      <div>
        <div className="driver-name">{d.name}</div>
        <div className="driver-tk mono">{d.ticker} · {d.session}</div>
      </div>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 16 }}>
        {d.spark && d.spark.length > 1 && (
          <Sparkline data={d.spark} color={up ? "var(--up)" : "var(--down)"} w={84} h={36} fill={false} strokeW={2} />
        )}
        <div className="driver-val">
          <div className="driver-px num">{d.value != null ? d.value.toLocaleString("ko-KR") : "—"}</div>
          <div className={"driver-ret num " + (up ? "up" : "down")}>{signPct(d.ret)}</div>
        </div>
      </div>
    </div>
  );
}
