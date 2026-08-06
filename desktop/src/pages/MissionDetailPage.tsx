import { useEffect, useRef, useState } from "react";

import { approveMission, cancelMission, missionEvents, missionStatus, onMissionLog, onMissionUpdated } from "../api";
import { DependencyGraph } from "../components/DependencyGraph";
import { LiveLog, type LogLine } from "../components/LiveLog";
import { StatusBadge } from "../components/StatusBadge";
import { formatClock, formatCost } from "../format";
import type { Route } from "../router";
import type { LedgerEvent, MissionStatus } from "../types";

function ledgerToLine(e: LedgerEvent): LogLine {
  const { ts, event, ...rest } = e;
  const fields = Object.entries(rest)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(" ");
  return {
    key: `${ts}-${event}-${Math.random().toString(36).slice(2, 7)}`,
    text: `[${formatClock(ts)}] ${event}${fields ? "  " + fields : ""}`,
  };
}

let lineSeq = 0;

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
  const [logLines, setLogLines] = useState<LogLine[]>([]);
  const [busy, setBusy] = useState<"approve" | "cancel" | null>(null);
  const missionIdRef = useRef(missionId);
  missionIdRef.current = missionId;

  const refetchStatus = () => {
    missionStatus(missionId).catch((e) => {
      onError(`ミッション状態の取得に失敗しました: ${String(e)}`);
      return null;
    }).then((s) => {
      if (s) setStatus(s);
    });
  };

  useEffect(() => {
    setStatus(null);
    setLogLines([]);

    let cancelled = false;

    missionStatus(missionId)
      .then((s) => {
        if (!cancelled) setStatus(s);
      })
      .catch((e) => onError(`ミッション状態の取得に失敗しました: ${String(e)}`));

    missionEvents(missionId, 100)
      .then((events) => {
        if (!cancelled) setLogLines(events.map(ledgerToLine));
      })
      .catch((e) => onError(`実行ログの取得に失敗しました: ${String(e)}`));

    const unlistenLog = onMissionLog((payload) => {
      if (payload.missionId !== missionIdRef.current) return;
      lineSeq += 1;
      setLogLines((prev) => [...prev, { key: `live-${lineSeq}`, text: payload.line }]);
    });
    const unlistenUpdated = onMissionUpdated((payload) => {
      if (payload.missionId !== missionIdRef.current) return;
      refetchStatus();
    });

    return () => {
      cancelled = true;
      unlistenLog.then((fn) => fn());
      unlistenUpdated.then((fn) => fn());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [missionId]);

  const hasAwaitingApproval = status?.tasks.some((t) => t.status === "awaiting_approval") ?? false;

  const handleApprove = async () => {
    setBusy("approve");
    try {
      await approveMission(missionId);
    } catch (e) {
      onError(`承認の実行に失敗しました: ${String(e)}`);
    } finally {
      setBusy(null);
    }
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
            <div style={{ display: "flex", gap: 8 }}>
              <button
                className={`btn btn-primary${hasAwaitingApproval ? " btn-emphasis" : ""}`}
                onClick={handleApprove}
                disabled={busy !== null || !hasAwaitingApproval}
                title={hasAwaitingApproval ? "承認待ちのタスクがあります" : "承認待ちのタスクはありません"}
              >
                {busy === "approve" ? <span className="spinner" /> : "✓"} 承認する
              </button>
              <button
                className="btn btn-danger"
                onClick={handleCancel}
                disabled={busy !== null || status.status !== "running"}
              >
                {busy === "cancel" ? <span className="spinner" /> : "✕"} キャンセル
              </button>
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

          <div className="panel">
            <div className="panel-title">ライブログ</div>
            <LiveLog lines={logLines} />
          </div>
        </>
      )}
    </div>
  );
}
