export function formatCost(usd: number): string {
  return `$${usd.toFixed(4)}`;
}

export function formatClock(tsSeconds: number): string {
  const d = new Date(tsSeconds * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** 起票・完了列用の "MM/DD HH:mm"。null(未完了・ledger欠落)は "--"。 */
export function formatDateTime(tsSeconds: number | null): string {
  if (tsSeconds === null) return "--";
  const d = new Date(tsSeconds * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
