import { ERROR_DETAIL_SEPARATOR } from "../errorClassify";

// message は「主要文言 + ERROR_DETAIL_SEPARATOR + 生エラーメッセージ」の
// 合成文字列(errorClassify.ts withDetail())を渡せる。区切りが無い従来通りの
// 単純な文字列は全文をそのまま1行表示する(後方互換)。判別できないエラーで
// 生メッセージを失わせない(P0-5)ため、詳細は折りたたみで必ず参照可能にする。
export function ErrorBanner({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  const sepIndex = message.indexOf(ERROR_DETAIL_SEPARATOR);
  const primary = sepIndex === -1 ? message : message.slice(0, sepIndex);
  const detail = sepIndex === -1 ? null : message.slice(sepIndex + ERROR_DETAIL_SEPARATOR.length);

  return (
    <div className="banner banner-error" role="alert">
      <span>⚠</span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div>{primary}</div>
        {detail !== null && (
          <details style={{ marginTop: 6 }}>
            <summary style={{ cursor: "pointer", fontSize: 12, opacity: 0.85 }}>詳細(元のエラーメッセージ)</summary>
            <pre
              className="mono"
              style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 11.5, marginTop: 4, opacity: 0.9 }}
            >
              {detail}
            </pre>
          </details>
        )}
      </div>
      <button className="banner-dismiss" onClick={onDismiss} aria-label="閉じる">
        ×
      </button>
    </div>
  );
}
