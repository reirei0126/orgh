import { useEffect, useRef, useState } from "react";

import { approveMission, cancelMission, missionEvents, missionStatus, onMissionLog, onMissionUpdated } from "../api";
import { DependencyGraph } from "../components/DependencyGraph";
import { LiveLog, type LogLine } from "../components/LiveLog";
import { StatusBadge } from "../components/StatusBadge";
import { formatClock, formatCost } from "../format";
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

let lineSeq = 0;

/** 実行中ミッションの進捗・ledgerを追う再取得間隔(ms)。
 * mission-updatedイベントは自プロセスが起動した子プロセスの節目でしか
 * 発火しないため、watchデーモン起動のミッションや実行途中の進捗は
 * ポーリングでしか追えない。 */
const DETAIL_POLL_MS = 5_000;

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
  // ライブ行(追記のみ)を分けて持つ。混ぜると再取得のたびに重複する
  const [ledgerLines, setLedgerLines] = useState<LogLine[]>([]);
  const [liveLines, setLiveLines] = useState<LogLine[]>([]);
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
    setLedgerLines([]);
    setLiveLines([]);

    let cancelled = false;

    const fetchAll = (reportError: boolean) => {
      missionStatus(missionId)
        .then((s) => {
          if (!cancelled) setStatus(s);
        })
        .catch((e) => {
          if (reportError) onError(`ミッション状態の取得に失敗しました: ${String(e)}`);
        });
      missionEvents(missionId, 100)
        .then((events) => {
          if (!cancelled) setLedgerLines(events.map(ledgerToLine));
        })
        .catch((e) => {
          if (reportError) onError(`実行ログの取得に失敗しました: ${String(e)}`);
        });
    };

    fetchAll(true);
    // ポーリング中の一時的な失敗はバナーを連発させない(次回成功で回復する)
    const timer = setInterval(() => fetchAll(false), DETAIL_POLL_MS);

    const unlistenLog = onMissionLog((payload) => {
      if (payload.missionId !== missionIdRef.current) return;
      lineSeq += 1;
      setLiveLines((prev) => [...prev, { key: `live-${lineSeq}`, text: payload.line }]);
    });
    const unlistenUpdated = onMissionUpdated((payload) => {
      if (payload.missionId !== missionIdRef.current) return;
      refetchStatus();
    });

    return () => {
      cancelled = true;
      clearInterval(timer);
      unlistenLog.then((fn) => fn());
      unlistenUpdated.then((fn) => fn());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [missionId]);

  const logLines = [...ledgerLines, ...liveLines];

  const hasAwaitingApproval = status?.tasks.some((t) => t.status === "awaiting_approval") ?? false;

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
                disabled={
                  busy !== null ||
                  (status.status !== "running" && status.status !== "awaiting_approval")
                }
                title="CANCELフラグを置き、実行中プロセスが検知した時点で停止します(即時停止ではありません)"
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
