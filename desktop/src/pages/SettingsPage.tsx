import { useEffect, useState } from "react";

import { doctor, getSettings, setSettings } from "../api";
import type { DoctorReport, Settings } from "../types";

export function SettingsPage({ onError }: { onError: (message: string) => void }) {
  const [form, setForm] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [report, setReport] = useState<DoctorReport | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    getSettings()
      .then(setForm)
      .catch((e) => onError(`設定の取得に失敗しました: ${String(e)}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const update = (patch: Partial<Settings>) => {
    setForm((prev) => (prev ? { ...prev, ...patch } : prev));
    setSaved(false);
  };

  const handleSave = async () => {
    if (!form) return;
    setSaving(true);
    try {
      await setSettings(form);
      setSaved(true);
    } catch (e) {
      onError(`設定の保存に失敗しました: ${String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  const handleDoctor = async () => {
    setChecking(true);
    setReport(null);
    try {
      setReport(await doctor());
    } catch (e) {
      onError(`診断の実行に失敗しました: ${String(e)}`);
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">設定</h1>
          <p className="page-subtitle">orgh CLIの接続先とGUIのローカル設定</p>
        </div>
      </div>

      {form === null && <div className="loading-row"><span className="spinner" />読み込み中…</div>}

      {form !== null && (
        <>
          <div className="panel" style={{ maxWidth: 640 }}>
            <div className="field">
              <label className="field-label" htmlFor="orgh-bin">orgh バイナリ</label>
              <input
                id="orgh-bin"
                className="input mono"
                value={form.orghBin}
                onChange={(e) => update({ orghBin: e.target.value })}
              />
              <span className="field-hint">絶対パス、またはPATH解決可能なコマンド名。</span>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="config-path">config.yaml のパス</label>
              <input
                id="config-path"
                className="input mono"
                value={form.configPath}
                onChange={(e) => update({ configPath: e.target.value })}
              />
              <span className="field-hint">全コマンドに <span className="mono">--config</span> として渡されます。</span>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="runs-dir">runs ディレクトリ</label>
              <input
                id="runs-dir"
                className="input mono"
                value={form.runsDir}
                onChange={(e) => update({ runsDir: e.target.value })}
              />
              <span className="field-hint">表示用のキャッシュ。実際の参照元は config.yaml の runs_dir。</span>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
              <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? <span className="spinner" /> : "保存する"}
              </button>
              {saved && <span className="cell-muted" style={{ fontSize: 12 }}>保存しました</span>}
            </div>
          </div>

          <div className="panel">
            <div className="panel-title">診断</div>
            <button className="btn" onClick={handleDoctor} disabled={checking}>
              {checking ? <span className="spinner" /> : "⟳"} orgh doctor を実行
            </button>

            {report !== null && (
              <div className="table-wrap" style={{ marginTop: 14 }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Check</th>
                      <th>OK</th>
                      <th>Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.checks.map((c) => (
                      <tr key={c.name}>
                        <td className="mono">{c.name}</td>
                        <td>
                          <span className="badge" style={{
                            color: c.ok ? "var(--success)" : "var(--danger)",
                            background: c.ok ? "var(--success-bg)" : "var(--danger-bg)",
                          }}>
                            {c.ok ? "ok" : "ng"}
                          </span>
                        </td>
                        <td className="cell-muted">{c.detail}</td>
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
