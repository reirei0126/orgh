import { useState } from "react";

import { ErrorBanner } from "./components/ErrorBanner";
import { MissionDetailPage } from "./pages/MissionDetailPage";
import { MissionListPage } from "./pages/MissionListPage";
import { NewMissionPage } from "./pages/NewMissionPage";
import { SettingsPage } from "./pages/SettingsPage";
import { useRoute } from "./router";

function App() {
  const [route, navigate] = useRoute();
  const [errors, setErrors] = useState<{ id: number; message: string }[]>([]);
  const onError = (message: string) => {
    setErrors((prev) => [...prev, { id: Date.now() + Math.random(), message }]);
  };
  const dismiss = (id: number) => setErrors((prev) => prev.filter((e) => e.id !== id));

  return (
    <div className="app-shell">
      <nav className="rail">
        <div className="rail-brand">
          <span className="rail-brand-mark" />
          <span className="rail-brand-name">orgh</span>
        </div>
        <button
          className={`rail-nav-item${route.name === "list" || route.name === "mission" ? " active" : ""}`}
          onClick={() => navigate({ name: "list" })}
        >
          ミッション
        </button>
        <button className={`rail-nav-item${route.name === "new" ? " active" : ""}`} onClick={() => navigate({ name: "new" })}>
          新規ミッション
        </button>
        <div className="rail-spacer" />
        <button className={`rail-nav-item${route.name === "settings" ? " active" : ""}`} onClick={() => navigate({ name: "settings" })}>
          設定
        </button>
      </nav>

      <main className="main">
        {errors.length > 0 && (
          <div style={{ padding: "16px 32px 0" }}>
            {errors.map((e) => (
              <ErrorBanner key={e.id} message={e.message} onDismiss={() => dismiss(e.id)} />
            ))}
          </div>
        )}

        {route.name === "list" && <MissionListPage navigate={navigate} onError={onError} />}
        {route.name === "new" && <NewMissionPage navigate={navigate} onError={onError} />}
        {route.name === "settings" && <SettingsPage onError={onError} />}
        {route.name === "mission" && (
          <MissionDetailPage missionId={route.missionId} navigate={navigate} onError={onError} />
        )}
      </main>
    </div>
  );
}

export default App;
