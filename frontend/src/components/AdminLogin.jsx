import { useEffect, useState } from "react";
import Icon from "./Icon.jsx";

// 데모 PIN. 실제 서비스에서는 서버 인증(이메일/비밀번호·세션)으로 교체.
const PIN = "1234";

export default function AdminLogin({ onClose, onSuccess }) {
  const [pin, setPin] = useState("");
  const [err, setErr] = useState(false);

  function push(d) {
    setErr(false);
    setPin((prev) => (prev.length >= 4 ? prev : prev + d));
  }
  function back() {
    setErr(false);
    setPin((p) => p.slice(0, -1));
  }

  useEffect(() => {
    if (pin.length < 4) return;
    if (pin === PIN) {
      const id = setTimeout(onSuccess, 200);
      return () => clearTimeout(id);
    }
    const id = setTimeout(() => { setErr(true); setPin(""); }, 260);
    return () => clearTimeout(id);
  }, [pin]); // eslint-disable-line react-hooks/exhaustive-deps

  // 물리 키보드 입력 지원
  useEffect(() => {
    function onKey(e) {
      if (e.key >= "0" && e.key <= "9") push(e.key);
      else if (e.key === "Backspace") back();
      else if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="modal-x" onClick={onClose} aria-label="닫기"><Icon name="close" size={18} /></button>
        <div className="modal-lock"><Icon name="shield" size={24} /></div>
        <div className="modal-title">관리자 인증</div>
        <div className="modal-sub">모델 학습·관리 메뉴는 관리자 전용입니다.<br />PIN을 입력하세요.</div>
        <div className={"pin-dots" + (err ? " shake" : "")}>
          {[0, 1, 2, 3].map((i) => (
            <span key={i} className={"pin-dot" + (i < pin.length ? " on" : "")} />
          ))}
        </div>
        <div className="pin-hint">
          {err ? <span className="down">PIN이 일치하지 않습니다</span> : <span>데모 PIN&nbsp;&nbsp;<strong>1234</strong></span>}
        </div>
        <div className="keypad">
          {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
            <button key={n} className="key" onClick={() => push(String(n))}>{n}</button>
          ))}
          <span />
          <button className="key" onClick={() => push("0")}>0</button>
          <button className="key key-fn" onClick={back} aria-label="지우기"><Icon name="back" size={20} /></button>
        </div>
      </div>
    </div>
  );
}
