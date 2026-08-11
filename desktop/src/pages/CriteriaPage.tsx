import { useEffect, useState } from "react";

import { criteriaApprove, criteriaList, criteriaReject } from "../api";
import type { CriteriaDraft, CriteriaEntry, CriteriaPayload } from "../types";

type Busy = { name: string; action: "approve" | "reject" } | null;

/** 下書きファイル名(<mission_id>-<n>)からミッションIDを取り出す
 * (orgh/criteria.py distill_verdict の採番規約に対応。CriteriaDraftに
 * sourceMissionフィールドは無く、nameから逆算する)。 */
function draftMissionId(name: string): string {
  const m = name.match(/^(.+)-\d+$/);
  return m ? m[1] : name;
}

function strengthTone(strength: string): { label: string; color: string; bg: string } {
  if (strength === "norm") return { label: "norm", color: "var(--info)", bg: "var(--info-bg)" };
  if (strength === "pref") return { label: "pref", color: "var(--muted)", bg: "var(--muted-bg)" };
  return { label: strength, color: "var(--text-dim)", bg: "var(--surface-hover)" };
}

function StrengthBadge({ strength }: { strength: string }) {
  const tone = strengthTone(strength);
  return (
    <span className="badge" style={{ color: tone.color, background: tone.bg }}>
      {tone.label}
    </span>
  );
}

function groupByCategory(entries: CriteriaEntry[]): [string, CriteriaEntry[]][] {
  const map = new Map<string, CriteriaEntry[]>();
  for (const e of entries) {
    const list = map.get(e.category) ?? [];
    list.push(e);
    map.set(e.category, list);
  }
  return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0]));
}

async function fetchCriteria(): Promise<CriteriaPayload> {
  return criteriaList();
}

export function CriteriaPage({ onError }: { onError: (message: string) => void }) {
  const [payload, setPayload] = useState<CriteriaPayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>(null);

  const load = () =>
    fetchCriteria()
      .then((result) => {
        setPayload(result);
        setLoadError(null);
      })
      .catch((e) => {
        setLoadError(String(e));
        onError(`基準台帳の取得に失敗しました: ${String(e)}`);
      });

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleAction = async (name: string, action: "approve" | "reject") => {
    setBusy({ name, action });
    try {
      if (action === "approve") await criteriaApprove(name);
      else await criteriaReject(name);
      await load();
    } catch (e) {
      onError(`下書き ${name} の${action === "approve" ? "承認" : "棄却"}に失敗しました: ${String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const grouped = payload ? groupByCategory(payload.entries) : [];

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">基準台帳</h1>
          <p className="page-subtitle">
            集計元: <span className="mono">orgh criteria list --json</span>。
            承認された基準だけが以後の全裁定に注入されます。
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
          <div className="empty-state">基準台帳を取得できませんでした: {loadError}</div>
        </div>
      )}

      {payload !== null && payload.skipped.length > 0 && (
        <div className="panel">
          <div className="empty-state">
            ⚠ 読み込めなかった項目を{payload.skipped.length}件、除外しました:
            {payload.skipped.map((sk) => (
              <div key={sk.path} className="mono">
                {sk.path} — {sk.reason}
              </div>
            ))}
          </div>
        </div>
      )}

      {payload !== null && (
        <>
          <div className="panel">
            <div className="panel-title">下書き(承認待ち)</div>
            {payload.drafts.length === 0 ? (
              <div className="empty-state">承認待ちの下書きはありません</div>
            ) : (
              <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 12 }}>
                {payload.drafts.map((d) => (
                  <DraftRow key={d.name} draft={d} busy={busy} onAction={handleAction} />
                ))}
              </ul>
            )}
          </div>

          <div className="panel">
            <div className="panel-title">本台帳</div>
            {grouped.length === 0 ? (
              <div className="empty-state">まだ本台帳に基準がありません。</div>
            ) : (
              grouped.map(([category, entries]) => (
                <div key={category} style={{ marginBottom: 20 }}>
                  <h2 style={{ fontSize: 13, fontWeight: 650, margin: "0 0 10px", color: "var(--text-dim)" }}>
                    {category}
                    <span className="cell-muted" style={{ marginLeft: 6, fontWeight: 500, fontSize: 11 }}>
                      ({entries.length}件)
                    </span>
                  </h2>
                  <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 10 }}>
                    {entries.map((e) => (
                      <EntryRow key={e.id} entry={e} />
                    ))}
                  </ul>
                </div>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}

function DraftRow({
  draft,
  busy,
  onAction,
}: {
  draft: CriteriaDraft;
  busy: Busy;
  onAction: (name: string, action: "approve" | "reject") => void;
}) {
  const isBusy = busy?.name === draft.name;

  return (
    <li className="panel" style={{ background: "var(--bg-elevated)" }}>
      {/* PROD-001: 判断材料(何を承認しようとしているのか)の一文をスクロール・展開なしで先頭に出す */}
      <p style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.6, margin: "0 0 10px" }}>
        {draft.text ?? "(本文なし — 下書きJSONを確認してください)"}
      </p>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
        {draft.strength !== null && <StrengthBadge strength={draft.strength} />}
        {draft.category !== null && <span className="cell-muted mono">{draft.category}</span>}
        <span className="cell-muted" style={{ fontSize: 11 }}>由来ミッション:</span>
        <span className="mono" style={{ fontSize: 11 }}>{draftMissionId(draft.name)}</span>
      </div>

      <details style={{ marginBottom: 14 }}>
        <summary style={{ cursor: "pointer", fontSize: 12, color: "var(--accent)" }}>詳細(下書きJSON)を見る</summary>
        <pre className="mono" style={{ fontSize: 11.5, whiteSpace: "pre-wrap", wordBreak: "break-word", marginTop: 8 }}>
          {JSON.stringify(draft.raw, null, 1)}
        </pre>
        <p className="field-hint mono" style={{ marginTop: 6 }}>{draft.path}</p>
      </details>

      <div style={{ display: "flex", gap: 10 }}>
        <button className="btn btn-primary" disabled={isBusy} onClick={() => onAction(draft.name, "approve")}>
          {isBusy && busy?.action === "approve" ? <span className="spinner" /> : "✓"} 承認
        </button>
        <button className="btn btn-danger" disabled={isBusy} onClick={() => onAction(draft.name, "reject")}>
          {isBusy && busy?.action === "reject" ? <span className="spinner" /> : "✕"} 棄却
        </button>
      </div>
    </li>
  );
}

function EntryRow({ entry }: { entry: CriteriaEntry }) {
  return (
    <li style={{ borderBottom: "1px solid var(--border)", paddingBottom: 10 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
        <span className="cell-id mono">{entry.id}</span>
        <StrengthBadge strength={entry.strength} />
        {entry.sourceMission !== null && (
          <span className="cell-muted" style={{ fontSize: 11 }}>
            由来: <span className="mono">{entry.sourceMission}</span>
          </span>
        )}
        {entry.date !== null && <span className="cell-muted" style={{ fontSize: 11 }}>{entry.date}</span>}
      </div>
      <div style={{ marginTop: 4 }}>{entry.text}</div>
    </li>
  );
}
