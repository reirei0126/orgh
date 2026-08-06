import { useEffect, useRef, useState } from "react";

import { startMission } from "../api";
import { getPendingLines, subscribePendingLog } from "../logStore";
import type { Route } from "../router";

type Mode = "intent" | "note";

export function NewMissionPage({ navigate, onError }: { navigate: (route: Route) => void; onError: (message: string) => void }) {
  const [mode, setMode] = useState<Mode>("intent");
  const [intent, setIntent] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [planningLines, setPlanningLines] = useState<string[]>([]);
  // setStateは同一レンダー内の連続クリックに間に合わない(旧レンダーの
  // canSubmitを参照して二重起動できてしまう)ため、同期ロックはrefで持つ
  const submittingRef = useRef(false);

  // planning中(ORGH_MISSION_ID確定前)の出力を起動画面にも表示する。
  // 遷移までスピナーしか出ないと、plannerが数分かかるとき進行が見えない
  useEffect(() => {
    if (!submitting) return;
    setPlanningLines([...getPendingLines()]);
    const unsub = subscribePendingLog(() => {
      setPlanningLines([...getPendingLines()]);
    });
    return unsub;
  }, [submitting]);

  const value = mode === "intent" ? intent : note;
  const canSubmit = value.trim().length > 0 && !submitting;

  const handleSubmit = async () => {
    if (submittingRef.current) return;
    if (value.trim().length === 0) return;
    submittingRef.current = true;
    setSubmitting(true);
    try {
      const missionId = await startMission(
        mode === "intent" ? intent.trim() : null,
        mode === "note" ? note.trim() : null,
      );
      navigate({ name: "mission", missionId });
    } catch (e) {
      onError(`ミッションの開始に失敗しました: ${String(e)}`);
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <div className="page">
      <div className="breadcrumb">
        <a onClick={() => navigate({ name: "list" })}>ミッション</a> / 新規
      </div>
      <div className="page-header">
        <div>
          <h1 className="page-title">新規ミッション</h1>
          <p className="page-subtitle">intentを直接書くか、既存ノートを指定してミッションを開始します</p>
        </div>
      </div>

      <div className="panel" style={{ maxWidth: 640 }}>
        <div className="radio-row">
          <label className="radio-option">
            <input type="radio" checked={mode === "intent"} onChange={() => setMode("intent")} />
            intent を直接入力
          </label>
          <label className="radio-option">
            <input type="radio" checked={mode === "note"} onChange={() => setMode("note")} />
            note 名を指定
          </label>
        </div>

        {mode === "intent" ? (
          <div className="field" style={{ marginTop: 12 }}>
            <label className="field-label" htmlFor="intent-input">intent</label>
            <textarea
              id="intent-input"
              className="textarea"
              placeholder={"やってほしいことを書く(複数行可)\n例: 料金ページのレスポンシブ崩れを直してください"}
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
            />
          </div>
        ) : (
          <div className="field" style={{ marginTop: 12 }}>
            <label className="field-label" htmlFor="note-input">note 名</label>
            <input
              id="note-input"
              className="input mono"
              placeholder="例: notes/2026-08-pricing-fix.md"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <span className="field-hint">vault内のノートパス、またはノート名を指定します。</span>
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 8 }}>
          <button className="btn" onClick={() => navigate({ name: "list" })} disabled={submitting}>
            キャンセル
          </button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? <span className="spinner" /> : "▶"} ミッションを開始
          </button>
        </div>

        {submitting && (
          <div className="field" style={{ marginTop: 12 }}>
            <span className="field-hint">
              planning中… ミッションIDが確定すると詳細画面へ移動します。
            </span>
            {planningLines.length > 0 && (
              <pre className="mono" style={{ fontSize: 12, maxHeight: 200, overflowY: "auto", marginTop: 6 }}>
                {planningLines.slice(-50).join("\n")}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
