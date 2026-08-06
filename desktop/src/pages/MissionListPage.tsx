import { useEffect, useState } from "react";

import { listMissions } from "../api";
import { StatusBadge } from "../components/StatusBadge";
import { formatCost } from "../format";
import type { ListPayload } from "../types";
import type { Route } from "../router";

/** 実行中ミッションの進捗を追うための再取得間隔(ms)。
 * mission-updatedイベントは自プロセス起動分しか飛ばないため、
 * watchデーモン等の外部起動ミッションはポーリングでしか追えない。 */
const LIST_POLL_MS = 10_000;

export function MissionListPage({ navigate, onError }: { navigate: (route: Route) => void; onError: (message: string) => void }) {
  const [payload, setPayload] = useState<ListPayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let reported = false;
    // ポーリング応答の逆転対策: 古い世代の応答でstateを上書きしない
    let generation = 0;
    const fetchList = () => {
      const gen = ++generation;
      listMissions()
        .then((result) => {
          if (cancelled || gen !== generation) return;
          setPayload(result);
          setLoadError(null);
          reported = false;
        })
        .catch((e) => {
          if (cancelled || gen !== generation) return;
          // 失敗状態を保持してスピナーを止める(初回未設定時に永久読み込みに
          // なるのを防ぐ)。バナーの多重表示は避けて失敗継続中は1回だけ通知
          setLoadError(String(e));
          if (!reported) {
            reported = true;
            onError(`ミッション一覧の取得に失敗しました: ${String(e)}`);
          }
        });
    };
    fetchList();
    const timer = setInterval(fetchList, LIST_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const missions = payload?.missions ?? null;

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

      {missions === null && loadError === null && (
        <div className="loading-row"><span className="spinner" />読み込み中…</div>
      )}

      {missions === null && loadError !== null && (
        <div className="panel">
          <div className="empty-state">
            ミッション一覧を取得できません: {loadError}
            <br />
            orghコマンドのパスとconfig.yamlの場所が正しいか
            <button className="btn" onClick={() => navigate({ name: "settings" })}>設定</button>
            から確認してください。
          </div>
        </div>
      )}

      {payload !== null && payload.skipped.length > 0 && (
        <div className="panel">
          <div className="empty-state">
            ⚠ 読み込めないミッションデータを{payload.skipped.length}件スキップしました
            (0件表示はデータ破損の可能性があります):
            {payload.skipped.map((s) => (
              <div key={s.path} className="mono">{s.path} — {s.reason}</div>
            ))}
          </div>
        </div>
      )}

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
