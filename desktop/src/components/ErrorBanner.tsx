export function ErrorBanner({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  return (
    <div className="banner banner-error" role="alert">
      <span>⚠</span>
      <span>{message}</span>
      <button className="banner-dismiss" onClick={onDismiss} aria-label="閉じる">
        ×
      </button>
    </div>
  );
}
