import Icon from "./Icon.jsx";
import { Pulse } from "./common.jsx";

export default function Sidebar({ route, onNav, nowLabel, isAdmin, onAdminEnter, onAdminExit }) {
  const items = [
    { id: "dashboard", label: "대시보드", ico: "grid" },
    { id: "detail", label: "종목 분석", ico: "candle" },
    { id: "simulator", label: "시나리오", ico: "sliders" },
  ];
  return (
    <aside className="rail">
      <div className="brand">
        <div className="brand-mark">AM</div>
        <div>
          <div className="brand-name">애프터마켓</div>
          <div className="brand-sub">반도체 시초가 예측</div>
        </div>
      </div>
      <div className="nav-label">메뉴</div>
      {items.map((it) => (
        <button key={it.id} className={"nav-item" + (route === it.id ? " active" : "")} onClick={() => onNav(it.id)}>
          <Icon name={it.ico} className="nav-ico" />
          {it.label}
        </button>
      ))}
      <div className="rail-spacer" />
      <div className="market-chip">
        <div className="mc-top"><Pulse /> 밤사이 세션 추적</div>
        <div className="mc-sub">
          한국 정규장 마감 후 미국 SOX·환율 변동을 실시간 반영합니다.<br />
          <strong style={{ color: "var(--text-2)" }}>현재 {nowLabel}</strong>
        </div>
      </div>

      {isAdmin ? (
        <div className="admin-zone">
          <div className="nav-label" style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 12px 6px", whiteSpace: "nowrap" }}>
            <Icon name="shield" size={13} style={{ color: "var(--accent-deep)" }} /> 관리자
          </div>
          <button className={"nav-item" + (route === "model" ? " active" : "")} onClick={() => onNav("model")}>
            <Icon name="cpu" className="nav-ico" />
            모델 상태
          </button>
          <button className="admin-out" onClick={onAdminExit}>
            <Icon name="logout" size={15} /> 관리자 모드 종료
          </button>
        </div>
      ) : (
        <button className="admin-enter" onClick={onAdminEnter}>
          <Icon name="lock" size={15} /> 관리자
        </button>
      )}
    </aside>
  );
}
