import { useEffect, useState } from "react";

import type { Route } from "../router";
import type { PlaybookEntry, PlaybookFile, PlaybookPayload } from "../types";

async function fetchPlaybooks(): Promise<PlaybookPayload> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<PlaybookPayload>("playbooks");
}

export function PlaybooksPage({ navigate, onError, filterMissionId }: {
  navigate: (route: Route) => void;
  onError: (message: string) => void;
  /** 指定時、このミッションが追記したエントリだけに絞り込む(詳細画面からの導線)。 */
  filterMissionId?: string;
}) {
  const [payload, setPayload] = useState<PlaybookPayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchPlaybooks()
      .then((result) => {
        if (cancelled) return;
        setPayload(result);
        setLoadError(null);
        setSelected((prev) => {
          if (prev) return prev;
          if (filterMissionId) {
            const hit = result.playbooks.find((p) =>
              p.entries.some((e) => e.missionId === filterMissionId),
            );
            if (hit) return hit.name;
          }
          return result.playbooks[0]?.name ?? null;
        });
      })
      .catch((e) => {
        if (cancelled) return;
        setLoadError(String(e));
        onError(`playbookの取得に失敗しました: ${String(e)}`);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const active: PlaybookFile | null = payload?.playbooks.find((p) => p.name === selected) ?? null;
  const visibleEntries =
    active === null
      ? []
      : filterMissionId
        ? active.entries.filter((e) => e.missionId === filterMissionId)
        : active.entries;
  const filterHitTotal =
    filterMissionId && payload
      ? payload.playbooks.reduce(
          (n, p) => n + p.entries.filter((e) => e.missionId === filterMissionId).length,
          0,
        )
      : 0;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Playbook</h1>
          <p className="page-subtitle">
            集計元: <span className="mono">orgh playbooks --json</span>。各行末尾の付記から、どのミッションのretroが追記したかが分かります。
          </p>
        </div>
      </div>

      {payload === null && loadError === null && (
        <div className="loading-row">
          <span className="spinner" />
          読み込み中…
        </div>
      )}

      {loadError !== null && payload === null && (
        <div className="panel">
          <div className="empty-state">playbookを取得できませんでした: {loadError}</div>
        </div>
      )}

      {payload !== null && payload.playbooks.length === 0 && (
        <div className="panel">
          <div className="empty-state">まだ記録がありません。ミッション完了後、Retroが自動的にここへ追記します。</div>
        </div>
      )}

      {filterMissionId && payload !== null && (
        <div className="panel">
          <div className="empty-state">
            ミッション <span className="mono">{filterMissionId}</span> が追記したエントリに絞り込み中
            (全ファイル合計 {filterHitTotal}件)。
            {filterHitTotal === 0 && " このミッションによる追記は見つかりませんでした(retro未実行、または教訓なし)。"}
            <button className="btn" style={{ marginLeft: 8 }} onClick={() => navigate({ name: "playbooks" })}>
              絞り込みを解除
            </button>
          </div>
        </div>
      )}

      {payload !== null && payload.playbooks.length > 0 && (
        <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
          <div className="panel" style={{ width: 220, flexShrink: 0 }}>
            <div className="panel-title">ファイル</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {payload.playbooks.map((p) => (
                <button
                  key={p.name}
                  className={`rail-nav-item${p.name === selected ? " active" : ""}`}
                  style={{ textAlign: "left" }}
                  onClick={() => {
                    setSelected(p.name);
                    setShowRaw(false);
                  }}
                >
                  {p.name}.md
                  <span className="cell-muted" style={{ marginLeft: 6, fontSize: 11 }}>
                    ({p.entries.length}件)
                  </span>
                </button>
              ))}
            </div>
          </div>

          {active !== null && (
            <div className="panel" style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div className="panel-title">{active.name}.md</div>
                <button className="btn" onClick={() => setShowRaw((v) => !v)}>
                  {showRaw ? "エントリ表示に戻す" : "元ファイルを表示"}
                </button>
              </div>
              <p className="field-hint mono" style={{ marginBottom: 10 }}>
                {active.path}
              </p>

              {showRaw ? (
                <pre className="mono" style={{ fontSize: 12, whiteSpace: "pre-wrap", maxHeight: 500, overflowY: "auto" }}>
                  {active.body}
                </pre>
              ) : visibleEntries.length === 0 ? (
                <div className="empty-state">
                  {filterMissionId
                    ? "このファイルには該当ミッションのエントリがありません。"
                    : "この行形式のエントリはまだありません(「元ファイルを表示」で全文を確認できます)。"}
                </div>
              ) : (
                <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 10 }}>
                  {visibleEntries.map((entry, i) => (
                    <PlaybookEntryRow key={i} entry={entry} navigate={navigate} />
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function PlaybookEntryRow({ entry, navigate }: { entry: PlaybookEntry; navigate: (route: Route) => void }) {
  return (
    <li style={{ borderBottom: "1px solid var(--border)", paddingBottom: 10 }}>
      <div>{entry.text}</div>
      <div style={{ marginTop: 4, display: "flex", gap: 8, alignItems: "center", fontSize: 11 }}>
        {entry.missionId !== null ? (
          <>
            <span className="cell-muted">追記元ミッション:</span>
            <a className="mono" onClick={() => navigate({ name: "mission", missionId: entry.missionId as string })}>
              {entry.missionId}
            </a>
          </>
        ) : (
          <span className="cell-muted">手動追記(対応するミッションなし)</span>
        )}
        {entry.date !== null && <span className="cell-muted">{entry.date}</span>}
      </div>
    </li>
  );
}
