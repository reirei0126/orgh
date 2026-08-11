import { useEffect, useRef, useState } from "react";

import { approveMission, cancelMission, missionEvents, missionStatus, onMissionUpdated } from "../api";
import { DependencyGraph } from "../components/DependencyGraph";
import { LiveLog, type LogLine } from "../components/LiveLog";
import { StatusBadge } from "../components/StatusBadge";
import { formatClock, formatCost } from "../format";
import { getLiveLines, subscribeLiveLog } from "../logStore";
import type { Route } from "../router";
import type { LedgerEvent, MissionStatus } from "../types";

function ledgerToLine(e: LedgerEvent, index: number): LogLine {
  const { ts, event, ...rest } = e;
  const fields = Object.entries(rest)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(" ");
  return {
    // ポーリングで同じ行を再取得しても同一keyになるよう、乱数ではなく
    // ts+event+取得内index で安定させる
    key: `${ts}-${event}-${index}`,
    text: `[${formatClock(ts)}] ${event}${fields ? "  " + fields : ""}`,
  };
}

/** 実行中ミッションの進捗・ledgerを追う再取得間隔(ms)。
 * mission-updatedイベントは自プロセスが起動した子プロセスの節目でしか
 * 発火しないため、watchデーモン起動のミッションや実行途中の進捗は
 * ポーリングでしか追えない。 */
const DETAIL_POLL_MS = 5_000;

// resume_mission は desktop/API.md §3.1.1 の契約により専用の非同期フロー
// (spawn成功=Ok即返し、承認確認行は無い)を持つ。既存の approveMission/
// cancelMission と異なりモックフォールバックを持つ desktop/src/api.ts の
// ラッパーが無いため(このタスクではapi.tsの編集範囲外)、api.tsのinvokeReal
// と同じ動的importパターンで直接invokeする。
async function resumeMission(missionId: string, retryFailed: boolean): Promise<void> {
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke<void>("resume_mission", { missionId, retryFailed });
}

export function MissionDetailPage({
  missionId,
  navigate,
  onError,
}: {
  missionId: string;
  navigate: (route: Route) => void;
  onError: (message: string) => void;
}) {
  const [status, setStatus] = useState<MissionStatus | null>(null);
  // ledger由来の行(ポーリングで全置換)と、実行中プロセスのstdout/stderr由来の
  // ライブ行(logStoreが一元管理・上限つき)を分けて持つ。混ぜると重複する
  const [ledgerLines, setLedgerLines] = useState<LogLine[]>([]);
  const [liveLines, setLiveLines] = useState<string[]>([]);
  const [busy, setBusy] = useState<"approve" | "cancel" | "resume" | null>(null);
  const [retryFailed, setRetryFailed] = useState(false);
  // PROD-001承認ダイアログ: 開閉状態と「詳細を見る」の展開状態を分けて持つ
  // (開くたびに詳細は畳んだ状態へ戻す)
  const [confirmApproveOpen, setConfirmApproveOpen] = useState(false);
  const [approvalDetailsOpen, setApprovalDetailsOpen] = useState(false);
  const missionIdRef = useRef(missionId);
  missionIdRef.current = missionId;
  // ポーリング応答の逆転対策: 古い世代の応答でstateを上書きしない
  const statusGenRef = useRef(0);
  const eventsGenRef = useRef(0);

  const refetchStatus = () => {
    const gen = ++statusGenRef.current;
    missionStatus(missionId).catch((e) => {
      onError(`ミッション状態の取得に失敗しました: ${String(e)}`);
      return null;
    }).then((s) => {
      if (s && gen === statusGenRef.current) setStatus(s);
    });
  };

  useEffect(() => {
    setStatus(null);
    setLedgerLines([]);
    setLiveLines(getLiveLines(missionId));

    let cancelled = false;

    const fetchAll = (reportError: boolean) => {
      const statusGen = ++statusGenRef.current;
      missionStatus(missionId)
        .then((s) => {
          if (!cancelled && statusGen === statusGenRef.current) setStatus(s);
        })
        .catch((e) => {
          if (reportError) onError(`ミッション状態の取得に失敗しました: ${String(e)}`);
        });
      const eventsGen = ++eventsGenRef.current;
      missionEvents(missionId, 100)
        .then((events) => {
          if (!cancelled && eventsGen === eventsGenRef.current) {
            setLedgerLines(events.map(ledgerToLine));
          }
        })
        .catch((e) => {
          if (reportError) onError(`実行ログの取得に失敗しました: ${String(e)}`);
        });
    };

    fetchAll(true);
    // ポーリング中の一時的な失敗はバナーを連発させない(次回成功で回復する)
    const timer = setInterval(() => fetchAll(false), DETAIL_POLL_MS);

    const unsubscribeLog = subscribeLiveLog(missionId, () => {
      setLiveLines([...getLiveLines(missionId)]);
    });
    const unlistenUpdated = onMissionUpdated((payload) => {
      if (payload.missionId !== missionIdRef.current) return;
      refetchStatus();
    });

    return () => {
      cancelled = true;
      clearInterval(timer);
      unsubscribeLog();
      unlistenUpdated.then((fn) => fn());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [missionId]);

  const logLines = [
    ...ledgerLines,
    ...liveLines.map((text, i) => ({ key: `live-${i}`, text })),
  ];

  const hasAwaitingApproval = status?.tasks.some((t) => t.status === "awaiting_approval") ?? false;
  // 再開可能なのは cancelled / failed のときのみ(running/done/awaiting_approvalでは
  // 「次にできる操作しかボタンが活性化されない」原則に従い、操作自体を出さない)
  const canResume = status !== null && (status.status === "cancelled" || status.status === "failed");

  const handleApprove = async () => {
    setBusy("approve");
    try {
      await approveMission(missionId);
      // approveは子プロセスをspawnして即座に戻る(実行自体は継続する)。
      // 承認直後の状態遷移(awaiting_approval→pending/running)を反映する
      refetchStatus();
    } catch (e) {
      onError(`承認の実行に失敗しました: ${String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  // 承認ボタン押下時のエントリポイント。approval_brief(orgh/status_json.py由来)が
  // あれば「何を承認するのか」を確認するダイアログを開く(PROD-001)。旧CLI/旧データで
  // approval_briefが無い場合は詳細を提示しようがないため、従来どおり即時承認する
  // (graceful degradation)
  const handleApproveClick = () => {
    if (status?.approvalBrief) {
      setApprovalDetailsOpen(false);
      setConfirmApproveOpen(true);
    } else {
      void handleApprove();
    }
  };

  const handleConfirmApprove = () => {
    setConfirmApproveOpen(false);
    void handleApprove();
  };

  const handleCancel = async () => {
    setBusy("cancel");
    try {
      await cancelMission(missionId);
      refetchStatus();
    } catch (e) {
      onError(`キャンセルの実行に失敗しました: ${String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const handleResume = async () => {
    setBusy("resume");
    try {
      await resumeMission(missionId, retryFailed);
      // resume_mission はspawn成功時点でOkを返す(§3.1.1)。実際に再開が
      // 受理されたかはmission-updated経由の再取得でのみ分かるため、
      // ここでも明示的に一度取得し直す(mission-updatedのemitを待たず即時反映)
      refetchStatus();
    } catch (e) {
      onError(`再開の実行に失敗しました: ${String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="page">
      <div className="breadcrumb">
        <a onClick={() => navigate({ name: "list" })}>ミッション</a> / <span className="mono">{missionId}</span>
      </div>

      {status === null && <div className="loading-row"><span className="spinner" />読み込み中…</div>}

      {status !== null && (
        <>
          <div className="page-header">
            <div>
              <h1 className="page-title">{status.intent}</h1>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
                <StatusBadge status={status.status} />
                <span className="mono cell-muted" style={{ fontSize: 12 }}>{status.missionId}</span>
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {canResume && (
                <label
                  style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}
                  className="cell-muted"
                >
                  <input
                    type="checkbox"
                    checked={retryFailed}
                    onChange={(e) => setRetryFailed(e.target.checked)}
                    disabled={busy !== null}
                  />
                  失敗タスクも含めて再試行する
                </label>
              )}
              <button
                className={`btn btn-primary${hasAwaitingApproval ? " btn-emphasis" : ""}`}
                onClick={handleApproveClick}
                disabled={busy !== null || !hasAwaitingApproval}
                title={hasAwaitingApproval ? "承認待ちのタスクがあります" : "承認待ちのタスクはありません"}
              >
                {busy === "approve" ? <span className="spinner" /> : "✓"} 承認する
              </button>
              <button
                className="btn btn-danger"
                onClick={handleCancel}
                disabled={
                  busy !== null ||
                  (status.status !== "running" && status.status !== "awaiting_approval")
                }
                title="CANCELフラグを置き、実行中プロセスが検知した時点で停止します(即時停止ではありません)"
              >
                {busy === "cancel" ? <span className="spinner" /> : "✕"} キャンセル
              </button>
              {canResume && (
                <button
                  className="btn btn-primary"
                  onClick={handleResume}
                  disabled={busy !== null}
                  title="キャンセル済み・失敗したミッションを再開します"
                >
                  {busy === "resume" ? <span className="spinner" /> : "↻"} 再開する
                </button>
              )}
            </div>
          </div>

          <div className="panel">
            <div className="panel-title">コスト / 予算</div>
            <div className="stat-row">
              <div className="stat">
                <span className="stat-label">Cost</span>
                <span className="stat-value">{formatCost(status.costUsd)}</span>
              </div>
              <div className="stat">
                <span className="stat-label">Budget</span>
                <span className="stat-value">{status.budgetUsd === null ? "無制限" : formatCost(status.budgetUsd)}</span>
              </div>
              <div className="stat">
                <span className="stat-label">Tasks</span>
                <span className="stat-value">
                  {status.tasks.filter((t) => t.status === "done").length}/{status.tasks.length}
                </span>
              </div>
            </div>
            {status.budgetUsd !== null && (
              <div className="budget-track">
                <div
                  className="budget-fill"
                  style={{
                    width: `${Math.min(100, (status.costUsd / status.budgetUsd) * 100)}%`,
                    background: status.costUsd / status.budgetUsd > 0.9 ? "var(--danger)" : "var(--accent)",
                  }}
                />
              </div>
            )}
          </div>

          <div className="panel">
            <div className="panel-title">タスク</div>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Title</th>
                    <th>Worker</th>
                    <th>Status</th>
                    <th>Attempts</th>
                    <th>Deps</th>
                  </tr>
                </thead>
                <tbody>
                  {status.tasks.map((t) => (
                    <tr key={t.id}>
                      <td className="cell-id">{t.id}</td>
                      <td>{t.title}</td>
                      <td className="mono cell-muted">{t.worker}</td>
                      <td><StatusBadge status={t.status} /></td>
                      <td className="mono">{t.attempts}</td>
                      <td className="mono cell-muted">{t.deps.length > 0 ? t.deps.join(", ") : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="panel">
            <div className="panel-title">依存関係(DAG)</div>
            <DependencyGraph tasks={status.tasks} />
          </div>

          {(status.status === "done" || status.status === "failed" || status.status === "cancelled") && (
            <div className="panel">
              <div className="panel-title">このミッションの学び</div>
              <p className="field-hint">
                完了・決着したミッションはRetroがplaybookへ教訓を追記します(教訓なしの場合もあります)。
              </p>
              <button className="btn" onClick={() => navigate({ name: "playbooks", missionId })}>
                Playbookでこのミッションの追記を見る
              </button>
            </div>
          )}

          <div className="panel">
            <div className="panel-title">ライブログ</div>
            <LiveLog lines={logLines} />
          </div>
        </>
      )}

      {confirmApproveOpen && status?.approvalBrief && (
        <div className="modal-overlay" onClick={() => setConfirmApproveOpen(false)}>
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="panel-title">承認の確認</div>
            <p className="modal-summary">{status.approvalBrief.summary}</p>
            <button
              type="button"
              className="modal-details-toggle"
              onClick={() => setApprovalDetailsOpen((v) => !v)}
            >
              {approvalDetailsOpen ? "▾ 詳細を隠す" : "▸ 詳細を見る"}
            </button>
            {approvalDetailsOpen && (
              <div className="modal-details">
                {status.approvalBrief.gatedTasks.map((t) => (
                  <div className="modal-gated-task" key={t.id}>
                    <div className="modal-gated-task-title">{t.title}</div>
                    <div className="modal-gated-task-meta">workdir: {t.workdir}</div>
                    <div className="modal-gated-task-meta">理由: {t.reason}</div>
                  </div>
                ))}
                <div className="modal-cost-line">消費済み: {formatCost(status.costUsd)}</div>
              </div>
            )}
            <div className="modal-actions">
              <button
                className="btn"
                onClick={() => setConfirmApproveOpen(false)}
                disabled={busy !== null}
              >
                キャンセル
              </button>
              <button
                className="btn btn-primary"
                onClick={handleConfirmApprove}
                disabled={busy !== null}
              >
                {busy === "approve" ? <span className="spinner" /> : "✓"} 承認して実行
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
