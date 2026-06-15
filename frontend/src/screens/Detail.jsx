import { useEffect, useState } from "react";
import Icon from "../components/Icon.jsx";
import { Topbar } from "../components/common.jsx";
import { CandleChart, SyncChart } from "../components/Charts.jsx";
import { api } from "../api.js";
import { won, signWon, signPct } from "../lib/format.js";

export default function Detail({ targets, pick, setPick, onRefresh, refreshing }) {
  const tg = targets.find((x) => x.key === pick) || targets[0];
  const [winN, setWinN] = useState(120);
  const [hist, setHist] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!tg) return;
    let alive = true;
    setLoading(true);
    setErr(null);
    api.history(tg.key, winN)
      .then((h) => { if (alive) setHist(h); })
      .catch((e) => { if (alive) setErr(e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [tg?.key, winN]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!tg) return null;
  const up = tg.predictedGap >= 0;
  const totalContrib = tg.contrib.reduce((a, b) => a + b.v, 0);
  const maxC = Math.max(1e-9, ...tg.contrib.map((c) => Math.abs(c.v)));

  return (
    <div className="screen-fade">
      <Topbar title="종목 분석" sub={tg.ticker + " · 캔들 · SOX 동조화 · 예측 분해"} onRefresh={onRefresh} refreshing={refreshing}>
        <div className="seg">
          {targets.map((x) => (
            <button key={x.key} className={x.key === pick ? "on" : ""} onClick={() => setPick(x.key)}>{x.key}</button>
          ))}
        </div>
      </Topbar>
      <div className="content">
        {err && <div className="banner error" style={{ margin: "0 0 16px" }}>⚠️ {err}</div>}
        <div className="grid" style={{ gridTemplateColumns: "1.7fr 1fr" }}>
          {/* 캔들 */}
          <div className="card pad">
            <div className="card-h" style={{ marginBottom: 14 }}>
              <div>
                <div className="card-title">{tg.key} 가격 추이</div>
                <div className="hero-ticker mono" style={{ marginTop: 3 }}>
                  종가 {won(tg.lastClose)}원 · 상승=<span className="up">빨강</span> / 하락=<span className="down">파랑</span>
                </div>
              </div>
              <div className="seg">
                {[60, 120, 250].map((w) => (
                  <button key={w} className={w === winN ? "on" : ""} onClick={() => setWinN(w)}>{w}일</button>
                ))}
              </div>
            </div>
            {loading || !hist
              ? <div className="skeleton" style={{ height: 360 }} />
              : <CandleChart ohlc={hist} height={360} />}
          </div>

          {/* 예측 분해 */}
          <div className="card pad">
            <div className="card-eyebrow">예상 시초가</div>
            <div className={"num " + (up ? "up" : "down")} style={{ fontSize: 34, fontWeight: 800, letterSpacing: "-0.03em", marginTop: 6 }}>
              {won(tg.estimatedOpen)}<span style={{ fontSize: 17, color: "var(--text-2)", marginLeft: 3 }}>원</span>
            </div>
            <div className={"hero-delta " + (up ? "up" : "down")} style={{ marginTop: 10 }}>
              <Icon name={up ? "arrowUp" : "arrowDown"} size={14} /> {signWon(tg.change)}원 · {signPct(tg.predictedGap)}
            </div>
            <div className="divider" />
            <div className="card-title" style={{ marginBottom: 4 }}>예측 갭 분해</div>
            <div className="disc" style={{ marginBottom: 10 }}>각 피처가 예상 갭 수익률에 기여한 정도 (%p)</div>
            {tg.contrib.length === 0 && <div className="disc">기여도 데이터가 없습니다.</div>}
            {tg.contrib.map((c, i) => (
              <div className="wf-row" key={i} style={{ gridTemplateColumns: "112px 1fr 52px" }}>
                <div className="wf-name">{c.name}</div>
                <div className="wf-bar">
                  <div className="wf-fill" style={{
                    left: "0%", width: (Math.abs(c.v) / maxC) * 100 + "%",
                    background: c.v >= 0 ? "var(--up)" : "var(--down)", opacity: 0.85,
                  }} />
                </div>
                <div className="wf-val">{c.v >= 0 ? "+" : "−"}{Math.abs(c.v).toFixed(2)}</div>
              </div>
            ))}
            {tg.contrib.length > 0 && (
              <div className="wf-row" style={{ gridTemplateColumns: "112px 1fr 52px", borderTop: "1px solid var(--border)", marginTop: 4, paddingTop: 12 }}>
                <div className="wf-name" style={{ fontWeight: 800, color: "var(--text)" }}>예측 갭 합계</div>
                <div />
                <div className={"wf-val " + (totalContrib >= 0 ? "up" : "down")}>{totalContrib >= 0 ? "+" : "−"}{Math.abs(totalContrib).toFixed(2)}</div>
              </div>
            )}
          </div>
        </div>

        {/* 동조화 */}
        <div className="card pad" style={{ marginTop: 18 }}>
          <div className="card-h" style={{ marginBottom: 14 }}>
            <div>
              <div className="card-title">SOX vs {tg.key} 동조화</div>
              <div className="hero-ticker" style={{ marginTop: 3 }}>최근 {winN}일 · 기준=100 정규화</div>
            </div>
            <div style={{ display: "flex", gap: 16 }}>
              <span className="chip"><span style={{ width: 9, height: 9, borderRadius: 9, background: "var(--accent)" }} /> {tg.key}</span>
              <span className="chip"><span style={{ width: 9, height: 9, borderRadius: 9, background: "#22b8cf" }} /> SOX</span>
            </div>
          </div>
          {loading || !hist
            ? <div className="skeleton" style={{ height: 300 }} />
            : <SyncChart seriesA={hist.norm_stock} seriesB={hist.norm_sox} />}
        </div>
      </div>
    </div>
  );
}
