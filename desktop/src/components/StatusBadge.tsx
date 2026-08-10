interface Tone {
  label: string;
  color: string;
  bg: string;
  pulse?: boolean;
}

// 表示ラベルは desktop/API.md §5 の対応表(第2期 P0-6)に従い日本語化する。
// キー(内部値)・色分け・パルス表示は変更しない — API通信・フィルタ条件・
// イベント判定はこの内部値文字列に依存しているため。
const TONES: Record<string, Tone> = {
  empty: { label: "タスクなし", color: "var(--muted)", bg: "var(--muted-bg)" },
  pending: { label: "待機中", color: "var(--muted)", bg: "var(--muted-bg)" },
  running: { label: "実行中", color: "var(--info)", bg: "var(--info-bg)", pulse: true },
  review: { label: "レビュー中", color: "var(--info)", bg: "var(--info-bg)", pulse: true },
  awaiting_approval: { label: "承認待ち", color: "var(--warn)", bg: "var(--warn-bg)", pulse: true },
  done: { label: "完了", color: "var(--success)", bg: "var(--success-bg)" },
  failed: { label: "失敗", color: "var(--danger)", bg: "var(--danger-bg)" },
  cancelled: { label: "キャンセル済み", color: "var(--muted)", bg: "var(--muted-bg)" },
  skipped: { label: "スキップ", color: "var(--muted)", bg: "var(--muted-bg)" },
};

function toneFor(status: string): Tone {
  return TONES[status] ?? { label: status, color: "var(--text-dim)", bg: "var(--surface-hover)" };
}

export function StatusBadge({ status }: { status: string }) {
  const tone = toneFor(status);
  return (
    <span
      className={`badge${tone.pulse ? " badge-pulse" : ""}`}
      style={{ color: tone.color, background: tone.bg }}
    >
      <span className="badge-dot" style={{ background: tone.color }} />
      {tone.label}
    </span>
  );
}
