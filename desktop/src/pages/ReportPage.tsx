import { useEffect, useState } from "react";

import { formatCost } from "../format";
import type { ReportPayload } from "../types";

/** 期間選択の候補。CLIの `orgh report --days N` の N に対応する。 */
const DAY_OPTIONS = [7, 14, 30, 90];

async function fetchReport(days: number): Promise<ReportPayload> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<ReportPayload>("report", { days });
}

function formatDuration(sec: number): string {
  if (sec <= 0) return "0秒";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  const parts: string[] = [];
  if (h > 0) parts.push(`${h}時間`);
  if (h > 0 || m > 0) parts.push(`${m}分`);
  parts.push(`${s}秒`);
  return parts.join("");
}

export function ReportPage({ onError }: { onError: (message: string) => void }) {
  const [days, setDays] = useState(7);
  const [payload, setPayload] = useState<ReportPayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchReport(days)
      .then((result) => {
        if (cancelled) return;
        setPayload(result);
        setLoadError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setLoadError(String(e));
        onError(`レポートの取得に失敗しました: ${String(e)}`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days]);

  const isEmpty =
    payload !== null && payload.weekly.length === 0 && payload.missions.length === 0 && payload.workers.length === 0;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">レポート</h1>
          <p className="page-subtitle">
            集計元: <span className="mono">orgh report --days {days} --json</span>(このマシンの runs/ 配下データをその都度再集計)
          </p>
        </div>
      </div>

      <div className="panel" style={{ maxWidth: 320 }}>
        <div className="field">
          <label className="field-label" htmlFor="report-days">集計期間</label>
          <select
            id="report-days"
            className="input"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            disabled={loading}
          >
            {DAY_OPTIONS.map((d) => (
              <option key={d} value={d}>
                直近{d}日間
              </option>
            ))}
          </select>
          <span className="field-hint">
            期間を変更すると <span className="mono">--days {days}</span> で再取得・再計算します。
          </span>
        </div>
      </div>

      {loading && payload === null && (
        <div className="loading-row">
          <span className="spinner" />
          読み込み中…
        </div>
      )}

      {loadError !== null && payload === null && (
        <div className="panel">
          <div className="empty-state">レポートを取得できませんでした: {loadError}</div>
        </div>
      )}

      {payload !== null && isEmpty && (
        <div className="panel">
          <div className="empty-state">直近{payload.days}日間に集計対象のミッションがありません。</div>
        </div>
      )}

      {payload !== null && !isEmpty && (
        <>
          <div className="panel">
            <div className="panel-title">週次の初回attempt合格率・差し戻し率</div>
            <p className="field-hint" style={{ marginBottom: 10 }}>
              集計元: ISO週単位(例 2026-W32)。単位は件数、および%(小数点四捨五入)。
            </p>
            {payload.weekly.length === 0 ? (
              <div className="empty-state">この期間の週次データはありません。</div>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>週</th>
                      <th>対象タスク数</th>
                      <th>初回合格</th>
                      <th>初回合格率</th>
                      <th>差し戻し</th>
                      <th>差し戻し率</th>
                    </tr>
                  </thead>
                  <tbody>
                    {payload.weekly.map((w) => (
                      <tr key={w.week}>
                        <td className="mono">{w.week}</td>
                        <td>{w.total}</td>
                        <td>{w.firstPass}</td>
                        <td>{w.firstPassPct}%</td>
                        <td>{w.rework}</td>
                        <td>{w.reworkPct}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="panel">
            <div className="panel-title">ミッション別コスト・所要時間</div>
            <p className="field-hint" style={{ marginBottom: 10 }}>
              集計元: 各ミッションの実行ログ。コストはUSD、所要時間は最初のイベント〜完了(無ければ最後のイベント)まで。
            </p>
            {payload.missions.length === 0 ? (
              <div className="empty-state">この期間のミッションデータはありません。</div>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Mission ID</th>
                      <th>Intent</th>
                      <th>Cost</th>
                      <th>所要時間</th>
                      <th>進捗</th>
                    </tr>
                  </thead>
                  <tbody>
                    {payload.missions.map((m) => (
                      <tr key={m.missionId}>
                        <td className="cell-id">{m.missionId}</td>
                        <td className="cell-intent" title={m.intent}>
                          {m.intent}
                        </td>
                        <td className="mono">{formatCost(m.costUsd)}</td>
                        <td className="mono">{formatDuration(m.durationSec)}</td>
                        <td>
                          {m.tasksDone}/{m.tasksTotal}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="panel">
            <div className="panel-title">worker別失敗率</div>
            <p className="field-hint" style={{ marginBottom: 10 }}>
              集計元: 各タスクのworker割当と結果(worker未割当のタスクは除外)。単位は件数、および%(小数点四捨五入)。
            </p>
            {payload.workers.length === 0 ? (
              <div className="empty-state">この期間のworker別データはありません。</div>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Worker</th>
                      <th>失敗</th>
                      <th>合計</th>
                      <th>失敗率</th>
                    </tr>
                  </thead>
                  <tbody>
                    {payload.workers.map((w) => (
                      <tr key={w.worker}>
                        <td className="mono">{w.worker}</td>
                        <td>{w.failed}</td>
                        <td>{w.total}</td>
                        <td>{w.failedPct}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
