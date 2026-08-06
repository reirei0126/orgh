interface Tone {
  label: string;
  color: string;
  bg: string;
  pulse?: boolean;
}

const TONES: Record<string, Tone> = {
  empty: { label: "empty", color: "var(--muted)", bg: "var(--muted-bg)" },
  pending: { label: "pending", color: "var(--muted)", bg: "var(--muted-bg)" },
  running: { label: "running", color: "var(--info)", bg: "var(--info-bg)", pulse: true },
  review: { label: "review", color: "var(--info)", bg: "var(--info-bg)", pulse: true },
  awaiting_approval: { label: "awaiting approval", color: "var(--warn)", bg: "var(--warn-bg)", pulse: true },
  done: { label: "done", color: "var(--success)", bg: "var(--success-bg)" },
  failed: { label: "failed", color: "var(--danger)", bg: "var(--danger-bg)" },
  cancelled: { label: "cancelled", color: "var(--muted)", bg: "var(--muted-bg)" },
  skipped: { label: "skipped", color: "var(--muted)", bg: "var(--muted-bg)" },
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
