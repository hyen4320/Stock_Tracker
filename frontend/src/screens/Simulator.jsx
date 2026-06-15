import { useEffect, useState } from "react";
import Icon from "../components/Icon.jsx";
import { Topbar } from "../components/common.jsx";
import { won, signWon, signPct } from "../lib/format.js";

export default function Simulator({ targets, drivers, onRefresh, refreshing }) {
  const liveSox = +((drivers.sox.ret || 0) * 100).toFixed(2);
  const liveFx = +((drivers.fx.ret || 0) * 100).toFixed(2);

  const [auto, setAuto] = useState(false);
  const [sox, setSox] = useState(liveSox);
  const [fx, setFx] = useState(liveFx);

  useEffect(() => { if (auto) { setSox(liveSox); setFx(liveFx); } }, [auto, liveSox, liveFx]);

  const sx = auto ? liveSox : sox, fxv = auto ? liveFx : fx;

  // 종목별 학습 민감도(β)로 예측 갭을 선형 추정
  function gapOf(tg) {
    return tg.sens.base + tg.sens.betaSox * (sx / 100) + tg.sens.betaFx * (fxv / 100);
  }

  const presets = [
    { name: "급락", sox: -5, fx: -1.2, tone: "down" },
    { name: "약세", sox: -2, fx: -0.4, tone: "down" },
    { name: "보합", sox: 0, fx: 0, tone: "" },
    { name: "현재 라이브", sox: liveSox, fx: liveFx, tone: "up" },
    { name: "강세", sox: 3, fx: 0.6, tone: "up" },
    { name: "급등", sox: 6, fx: 1.5, tone: "up" },
  ];
  function applyPreset(p) { setAuto(false); setSox(p.sox); setFx(p.fx); }

  return (
    <div className="screen-fade">
      <Topbar title="시나리오 시뮬레이터" sub="SOX·환율 변동을 직접 넣어 예상 시초가를 실험" onRefresh={onRefresh} refreshing={refreshing} />
      <div className="content">
        <div className="grid" style={{ gridTemplateColumns: "1fr 1.25fr" }}>
          {/* 컨트롤 */}
          <div className="card pad">
            <div className="card-h" style={{ marginBottom: 18 }}>
              <div className="card-title">밤사이 변동 입력</div>
              <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                <span style={{ fontSize: 12.5, fontWeight: 700, color: auto ? "var(--accent-deep)" : "var(--text-3)", whiteSpace: "nowrap" }}>실시간 자동</span>
                <div className={"toggle-sw" + (auto ? " on" : "")} onClick={() => setAuto(!auto)}><i /></div>
              </div>
            </div>

            <div className="sld-row" style={{ opacity: auto ? 0.55 : 1, pointerEvents: auto ? "none" : "auto" }}>
              <div className="sld-head">
                <span className="lab"><Icon name="activity" size={14} style={{ verticalAlign: -2, marginRight: 5, color: "#2f7af6" }} />SOX 변동률</span>
                <span className={"val num " + (sx >= 0 ? "up" : "down")}>{sx >= 0 ? "+" : "−"}{Math.abs(sx).toFixed(2)}%</span>
              </div>
              <input className="sld" type="range" min={-8} max={8} step={0.1} value={sox} onChange={(e) => setSox(+e.target.value)} />
              <div className="sld-ticks"><span>−8%</span><span>0</span><span>+8%</span></div>
            </div>

            <div className="sld-row" style={{ marginTop: 22, opacity: auto ? 0.55 : 1, pointerEvents: auto ? "none" : "auto" }}>
              <div className="sld-head">
                <span className="lab"><Icon name="won" size={14} style={{ verticalAlign: -2, marginRight: 5, color: "var(--accent-deep)" }} />원/달러 변동률</span>
                <span className={"val num " + (fxv >= 0 ? "up" : "down")}>{fxv >= 0 ? "+" : "−"}{Math.abs(fxv).toFixed(2)}%</span>
              </div>
              <input className="sld" type="range" min={-3} max={3} step={0.05} value={fx} onChange={(e) => setFx(+e.target.value)} />
              <div className="sld-ticks"><span>−3%</span><span>0</span><span>+3%</span></div>
            </div>

            <div className="divider" />
            <div className="card-eyebrow" style={{ marginBottom: 10 }}>시나리오 프리셋</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
              {presets.map((p) => (
                <button key={p.name} className="btn" style={{ justifyContent: "center", padding: "10px 8px" }} onClick={() => applyPreset(p)}>
                  <span className={p.tone}>{p.name}</span>
                </button>
              ))}
            </div>
          </div>

          {/* 결과 */}
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            {targets.map((tg) => {
              const gap = gapOf(tg);
              const est = tg.lastClose * (1 + gap);
              const chg = est - tg.lastClose;
              const up = gap >= 0;
              const vsBase = gap - tg.predictedGap;
              const vsUp = vsBase >= -0.00005;
              return (
                <div className="card pad" key={tg.key}>
                  <div className="hero-top">
                    <div>
                      <div className="hero-name">{tg.key}</div>
                      <div className="hero-ticker mono">{tg.ticker}</div>
                    </div>
                    <div className="hero-logo" style={{ background: tg.logoBg }}>{tg.logo}</div>
                  </div>
                  <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginTop: 16 }}>
                    <div>
                      <div className="hero-est-label" style={{ margin: 0 }}>예상 시초가</div>
                      <div className={"num " + (up ? "up" : "down")} style={{ fontSize: 38, fontWeight: 800, letterSpacing: "-0.035em", lineHeight: 1 }}>
                        {won(est)}<span style={{ fontSize: 18, color: "var(--text-2)", marginLeft: 3 }}>원</span>
                      </div>
                      <div className={"hero-delta " + (up ? "up" : "down")} style={{ marginTop: 12 }}>
                        <Icon name={up ? "arrowUp" : "arrowDown"} size={14} /> {signWon(chg)}원 · {signPct(gap)}
                      </div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div className="driver-tk" style={{ marginBottom: 4 }}>라이브 대비</div>
                      <div className={"num " + (vsUp ? "up" : "down")} style={{ fontSize: 16, fontWeight: 800 }}>
                        {vsUp ? "+" : "−"}{Math.abs(vsBase * 100).toFixed(2)}%p
                      </div>
                    </div>
                  </div>
                  <div className="divider" />
                  <div style={{ display: "flex", gap: 26 }}>
                    <div className="stat"><div className="k">SOX 민감도 β</div><div className="v num">{tg.sens.betaSox.toFixed(2)}</div></div>
                    <div className="stat"><div className="k">환율 민감도 β</div><div className="v num">{tg.sens.betaFx.toFixed(2)}</div></div>
                    <div className="stat"><div className="k">전일 종가</div><div className="v num" style={{ color: "var(--text-2)" }}>{won(tg.lastClose)}</div></div>
                  </div>
                </div>
              );
            })}
            <p className="disc">SOX가 1%p 오르면 예상 갭은 종목별 β만큼 변동합니다. β는 학습된 모델의 평균 반응도입니다.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
