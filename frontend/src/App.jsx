import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { metaFor } from "./lib/meta.js";
import { kstNowLabel, signPct } from "./lib/format.js";
import Sidebar from "./components/Sidebar.jsx";
import AdminLogin from "./components/AdminLogin.jsx";
import Dashboard from "./screens/Dashboard.jsx";
import Detail from "./screens/Detail.jsx";
import Simulator from "./screens/Simulator.jsx";
import Model from "./screens/Model.jsx";

// 한국 정규장 마감(15:30) → 다음 개장(09:00) 사이 진행률 (0~1)
function overnightProgress() {
  const parts = new Intl.DateTimeFormat("en-US", {
    hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Seoul",
  }).formatToParts(new Date());
  const h = +parts.find((p) => p.type === "hour").value % 24;
  const m = +parts.find((p) => p.type === "minute").value;
  const mins = h * 60 + m;
  const start = 15 * 60 + 30; // 15:30
  const end = 9 * 60;         // 익일 09:00
  // 마감~자정(8.5h) + 자정~개장(9h) = 17.5h 윈도우
  let elapsed;
  if (mins >= start) elapsed = mins - start;
  else if (mins <= end) elapsed = 24 * 60 - start + mins;
  else return 1; // 장중: 다음 사이클 전까지는 완료로 표시
  return Math.max(0, Math.min(1, elapsed / (24 * 60 - start + end)));
}

function buildTimeline(soxRet) {
  return {
    nowLabel: kstNowLabel(),
    progress: overnightProgress(),
    nodes: [
      { t: "한국 마감", d: "어제 15:30", state: "done", price: "확정" },
      { t: "美 SOX 세션", d: "밤사이 · 진행중", state: "live", price: soxRet != null ? signPct(soxRet) : "—" },
      { t: "한국 시초가", d: "오늘 09:00", state: "pending", price: "예측" },
    ],
  };
}

export default function App() {
  const [route, setRoute] = useState("dashboard");
  const [isAdmin, setIsAdmin] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);

  const [targetObjs, setTargetObjs] = useState([]);
  const [drivers, setDrivers] = useState({
    sox: { name: "필라델피아 반도체지수", ticker: "^SOX", ret: 0, session: "미국 세션", value: null },
    fx: { name: "원/달러 환율", ticker: "KRW=X", ret: 0, session: "24시간", value: null },
  });
  const [timeline, setTimeline] = useState(buildTimeline(null));
  const [avgMae, setAvgMae] = useState(null);
  const [pick, setPick] = useState(null);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [nowLabel, setNowLabel] = useState(kstNowLabel());

  const load = useCallback(async () => {
    setError(null);
    try {
      const [preds, live, acc] = await Promise.all([
        api.predict().catch(() => []),
        api.liveDrivers().catch(() => ({ sox_ret: null, fx_ret: null })),
        api.accuracy().catch(() => []),
      ]);

      const objs = preds.map((p, i) => ({
        key: p.target,
        ...metaFor(p.target, i),
        lastClose: p.last_close,
        predictedGap: p.predicted_gap,
        estimatedOpen: p.estimated_open,
        change: p.change,
        actualOpen: p.actual_open,
        errorPct: p.error_pct,
      }));
      setTargetObjs(objs);
      if (objs.length && !pick) setPick(objs[0].key);

      setDrivers({
        sox: { name: "필라델피아 반도체지수", ticker: "^SOX", ret: live.sox_ret ?? 0, session: "미국 세션", value: null },
        fx: { name: "원/달러 환율", ticker: "KRW=X", ret: live.fx_ret ?? 0, session: "24시간", value: null },
      });
      setTimeline(buildTimeline(live.sox_ret));

      const withN = acc.filter((a) => a.n > 0 && a.mae_pct != null);
      setAvgMae(withN.length ? withN.reduce((s, a) => s + a.mae_pct, 0) / withN.length : null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [pick]);

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // 현재 시각(KST) 분 단위 갱신
  useEffect(() => {
    const id = setInterval(() => {
      setNowLabel(kstNowLabel());
      setTimeline((t) => ({ ...t, nowLabel: kstNowLabel(), progress: overnightProgress() }));
    }, 60000);
    return () => clearInterval(id);
  }, []);

  async function onRefresh() {
    setRefreshing(true);
    try {
      await api.refresh().catch(() => {});
      await load();
    } finally {
      setRefreshing(false);
    }
  }

  function goDetail(key) { if (key) setPick(key); setRoute("detail"); }
  function exitAdmin() { setIsAdmin(false); if (route === "model") setRoute("dashboard"); }

  const activeRoute = route === "model" && !isAdmin ? "dashboard" : route;
  const noData = !loading && targetObjs.length === 0;

  return (
    <div className="shell">
      <Sidebar
        route={activeRoute}
        onNav={setRoute}
        nowLabel={nowLabel}
        isAdmin={isAdmin}
        onAdminEnter={() => setLoginOpen(true)}
        onAdminExit={exitAdmin}
      />
      <main className="main">
        {error && <div className="banner error" style={{ marginTop: 22 }}>⚠️ {error}</div>}

        {loading && (
          <div className="content" style={{ paddingTop: 40 }}>
            <div className="skeleton" style={{ height: 120, marginBottom: 18 }} />
            <div className="hero-grid">
              <div className="skeleton" style={{ height: 240 }} />
              <div className="skeleton" style={{ height: 240 }} />
            </div>
            <p className="disc" style={{ marginTop: 16 }}>예측을 불러오는 중… 최초 실행은 모델 학습으로 1~2분 걸릴 수 있습니다.</p>
          </div>
        )}

        {noData && (
          <div className="content" style={{ paddingTop: 40 }}>
            <div className="card pad" style={{ textAlign: "center" }}>
              <div className="card-title" style={{ marginBottom: 8 }}>아직 예측 데이터가 없습니다</div>
              <p className="disc" style={{ marginBottom: 16 }}>예측 배치를 한 번 실행하면 오늘자 예상 시초가가 생성됩니다.</p>
              <button className="btn accent" style={{ justifyContent: "center" }} onClick={async () => {
                setLoading(true);
                await api.runPrediction().catch((e) => setError(e.message));
                await load();
              }}>예측 생성하기</button>
            </div>
          </div>
        )}

        {!loading && !noData && activeRoute === "dashboard" && (
          <Dashboard targets={targetObjs} drivers={drivers} timeline={timeline} avgMae={avgMae}
            onRefresh={onRefresh} refreshing={refreshing} goDetail={goDetail} />
        )}
        {!loading && !noData && activeRoute === "detail" && (
          <Detail targets={targetObjs} pick={pick} setPick={setPick} onRefresh={onRefresh} refreshing={refreshing} />
        )}
        {!loading && !noData && activeRoute === "simulator" && (
          <Simulator targets={targetObjs} drivers={drivers} onRefresh={onRefresh} refreshing={refreshing} />
        )}
        {!loading && activeRoute === "model" && isAdmin && (
          <Model onRefresh={onRefresh} refreshing={refreshing} />
        )}
      </main>

      {loginOpen && (
        <AdminLogin
          onClose={() => setLoginOpen(false)}
          onSuccess={() => { setIsAdmin(true); setLoginOpen(false); setRoute("model"); }}
        />
      )}
    </div>
  );
}
