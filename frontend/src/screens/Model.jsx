import { useEffect, useRef, useState } from "react";
import Icon from "../components/Icon.jsx";
import { Topbar } from "../components/common.jsx";
import { api } from "../api.js";

export default function Model({ onRefresh, refreshing }) {
  const [status, setStatus] = useState([]);   // [{target, trained}]
  const [acc, setAcc] = useState([]);          // [{target, n, mae_pct, direction_hit_rate}]
  const [metrics, setMetrics] = useState({});  // {target: {cv_mae, baseline_mae, improvement_pct, n_samples}}
  const [training, setTraining] = useState(false);
  const [prog, setProg] = useState(0);
  const [err, setErr] = useState(null);
  const progTimer = useRef(null);

  async function load() {
    try {
      const [s, a] = await Promise.all([api.modelStatus(), api.accuracy()]);
      setStatus(s);
      setAcc(a);
    } catch (e) {
      setErr(e.message);
    }
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function retrain() {
    setTraining(true);
    setProg(6);
    setErr(null);
    // 실제 학습이 끝날 때까지 천천히 90%까지 차오르는 진행바
    progTimer.current = setInterval(() => {
      setProg((p) => (p >= 90 ? 90 : p + 3));
    }, 220);
    try {
      const res = await api.train(); // [{target, n_samples, cv_mae, baseline_mae, improvement_pct}]
      const byTarget = {};
      res.forEach((m) => { byTarget[m.target] = m; });
      setMetrics(byTarget);
      await load();
      setProg(100);
    } catch (e) {
      setErr(e.message);
    } finally {
      clearInterval(progTimer.current);
      setTimeout(() => { setTraining(false); setProg(0); }, 500);
    }
  }

  const accOf = (name) => acc.find((a) => a.target === name);

  return (
    <div className="screen-fade">
      <Topbar title="모델 상태" sub="HistGradientBoostingRegressor · TimeSeriesSplit 5-fold · 지표 MAE" onRefresh={onRefresh} refreshing={refreshing}>
        <span className="badge warn"><Icon name="shield" size={12} /> 관리자 전용</span>
        <button className="btn accent" onClick={retrain} disabled={training}>
          <Icon name="brain" className="ico" /> {training ? "학습 중…" : "모델 재학습"}
        </button>
      </Topbar>
      <div className="content">
        {err && <div className="banner error" style={{ margin: "0 0 16px" }}>⚠️ {err}</div>}

        {training && (
          <div className="card pad" style={{ marginBottom: 18 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
              <span className="card-title">두 종목 모델 재학습 중…</span>
              <span className="num" style={{ fontWeight: 800, color: "var(--accent-deep)" }}>{prog}%</span>
            </div>
            <div style={{ height: 8, borderRadius: 6, background: "var(--surface-3)", overflow: "hidden" }}>
              <div style={{ width: prog + "%", height: "100%", background: "var(--accent)", transition: "width .2s" }} />
            </div>
          </div>
        )}

        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          {status.map((m) => {
            const a = accOf(m.target);
            const mt = metrics[m.target];
            const mae = mt ? mt.cv_mae : a && a.n ? a.mae_pct : null;
            const baseline = mt ? mt.baseline_mae : null;
            const improvement = mt ? mt.improvement_pct / 100 : null;
            const samples = mt ? mt.n_samples : a ? a.n : null;
            const hit = a && a.n ? a.direction_hit_rate : null;
            return (
              <div className="card pad" key={m.target}>
                <div className="card-h">
                  <div className="card-title">{m.target}</div>
                  {m.trained
                    ? <span className="badge ok"><Icon name="check" size={12} /> 학습됨</span>
                    : <span className="badge muted">미학습</span>}
                </div>
                <div className="statline" style={{ marginTop: 16 }}>
                  <div className="stat"><div className="k">MAE</div><div className="v num">{mae != null ? mae.toFixed(4) : "—"}</div></div>
                  <div className="stat"><div className="k">베이스라인</div><div className="v num" style={{ color: "var(--text-3)" }}>{baseline != null ? baseline.toFixed(4) : "—"}</div></div>
                  <div className="stat"><div className="k">개선율</div><div className="v num up">{improvement != null ? "−" + (improvement * 100).toFixed(1) + "%" : "—"}</div></div>
                </div>
                <div className="divider" />
                <div className="card-eyebrow" style={{ marginBottom: 12 }}>방향 적중률 (실제값 기준)</div>
                {hit != null ? (
                  <>
                    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 8 }}>
                      <span className="num" style={{ fontSize: 26, fontWeight: 800 }}>{(hit * 100).toFixed(0)}%</span>
                      <span className="disc">표본 {a.n}건</span>
                    </div>
                    <div style={{ height: 10, borderRadius: 6, background: "var(--surface-3)", overflow: "hidden" }}>
                      <div style={{ width: hit * 100 + "%", height: "100%", background: "var(--accent)", opacity: 0.85, borderRadius: 6 }} />
                    </div>
                  </>
                ) : (
                  <div className="disc">아직 실제 시초가가 기록된 예측이 없습니다. 다음 개장 이후 집계됩니다.</div>
                )}
                <div className="divider" />
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, color: "var(--text-2)" }}>
                  <span>학습 표본 <strong className="num" style={{ color: "var(--text)" }}>{samples != null ? samples.toLocaleString() : "—"}</strong></span>
                  <span className="mono">{mt ? "방금 재학습됨" : m.trained ? "학습 완료" : "미학습"}</span>
                </div>
              </div>
            );
          })}
        </div>

        <div className="card pad" style={{ marginTop: 18 }}>
          <div className="card-title" style={{ marginBottom: 6 }}>모델 구성</div>
          <table className="tbl">
            <thead><tr><th>항목</th><th>값</th><th>설명</th></tr></thead>
            <tbody>
              <tr><td>알고리즘</td><td className="mono">HistGradientBoostingRegressor</td><td className="muted">의존성 없는 그래디언트 부스팅</td></tr>
              <tr><td>타깃 y</td><td className="muted">종가[D] → 시초가[D+1] 갭 수익률</td><td className="muted">밤사이 갭을 예측</td></tr>
              <tr><td>피처 X</td><td className="muted">SOX·환율 수익률, 모멘텀, 시차</td><td className="muted">시간대 정렬</td></tr>
              <tr><td>검증</td><td className="mono">TimeSeriesSplit · 5-fold</td><td className="muted">미래 누수 방지</td></tr>
              <tr><td>데이터 소스</td><td className="mono">yfinance</td><td className="muted">무료 · 키 불필요</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
