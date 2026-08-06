import { useEffect, useState } from "react";

import { listMissions } from "../api";
import { StatusBadge } from "../components/StatusBadge";
import { formatCost } from "../format";
import type { MissionSummary } from "../types";
import type { Route } from "../router";

export function MissionListPage({ navigate, onError }: { navigate: (route: Route) => void; onError: (message: string) => void }) {
  const [missions, setMissions] = useState<MissionSummary[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    listMissions()
      .then((result) => {
        if (!cancelled) setMissions(result);
      })
      .catch((e) => onError(`ミッション一覧の取得に失敗しました: ${String(e)}`));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">ミッション</h1>
          <p className="page-subtitle">orgh が管理する全ミッションの一覧</p>
        </div>
        <button className="btn btn-primary" onClick={() => navigate({ name: "new" })}>
          + 新規ミッション
        </button>
      </div>

      {missions === null && <div className="loading-row"><span className="spinner" />読み込み中…</div>}

      {missions !== null && missions.length === 0 && (
        <div className="panel">
          <div className="empty-state">まだミッションがありません。「+ 新規ミッション」から開始できます。</div>
        </div>
      )}

      {missions !== null && missions.length > 0 && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Mission ID</th>
                <th>Intent</th>
                <th>Status</th>
                <th>進捗</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {missions.map((m) => (
                <tr key={m.missionId} className="clickable" onClick={() => navigate({ name: "mission", missionId: m.missionId })}>
                  <td className="cell-id">{m.missionId}</td>
                  <td className="cell-intent" title={m.intent}>{m.intent}</td>
                  <td><StatusBadge status={m.status} /></td>
                  <td>
                    <div className="progress-row">
                      <div className="progress-track">
                        <div
                          className="progress-fill"
                          style={{ width: `${m.tasksTotal === 0 ? 0 : (m.tasksDone / m.tasksTotal) * 100}%` }}
                        />
                      </div>
                      <span className="progress-label">{m.tasksDone}/{m.tasksTotal}</span>
                    </div>
                  </td>
                  <td className="mono">{formatCost(m.costUsd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
