import { useEffect, useRef } from "react";

export interface LogLine {
  key: string;
  text: string;
}

export function LiveLog({ lines }: { lines: LogLine[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  return (
    <div className="live-log" ref={scrollRef}>
      {lines.length === 0 && <div className="live-log-empty">ログはまだありません。</div>}
      {lines.map((line) => (
        <div className="live-log-line" key={line.key}>
          {line.text}
        </div>
      ))}
    </div>
  );
}
