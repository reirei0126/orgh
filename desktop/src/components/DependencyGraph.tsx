import type { TaskStatus } from "../types";
import { StatusBadge } from "./StatusBadge";

// タスクの依存関係を「深さ」でレイヤ分けして左→右に並べる簡易DAG表示。
// 矢印は描かず、各カードの依存先IDをチップで示すことで依存が読み取れるようにする。
interface GraphResult {
  layers: TaskStatus[][];
  /** 循環依存に巻き込まれているタスクID(実行側では永遠にreadyにならない)。 */
  cyclic: Set<string>;
  /** 存在しないタスクIDへの依存: taskId → 欠損している依存ID群。 */
  missingDeps: Map<string, string[]>;
}

function computeLayers(tasks: TaskStatus[]): GraphResult {
  const byId = new Map(tasks.map((t) => [t.id, t]));
  const depth = new Map<string, number>();
  const cyclic = new Set<string>();
  const missingDeps = new Map<string, string[]>();

  for (const t of tasks) {
    const missing = t.deps.filter((d) => !byId.has(d));
    if (missing.length > 0) missingDeps.set(t.id, missing);
  }

  function depthOf(id: string, guard: Set<string>): number {
    if (depth.has(id)) return depth.get(id) as number;
    if (guard.has(id)) {
      // 循環依存: Planner出力かmission.jsonの欠陥。正常なLayer 0として
      // 描画すると実行が進まない原因がGUIから見えなくなるため記録する
      cyclic.add(id);
      return 0;
    }
    const task = byId.get(id);
    if (!task || task.deps.length === 0) {
      depth.set(id, 0);
      return 0;
    }
    guard.add(id);
    const d = 1 + Math.max(...task.deps.map((dep) => (byId.has(dep) ? depthOf(dep, guard) : 0)));
    guard.delete(id);
    depth.set(id, d);
    return d;
  }

  for (const t of tasks) depthOf(t.id, new Set());

  const maxDepth = tasks.length === 0 ? -1 : Math.max(...tasks.map((t) => depth.get(t.id) ?? 0));
  const layers: TaskStatus[][] = Array.from({ length: maxDepth + 1 }, () => []);
  for (const t of tasks) layers[depth.get(t.id) ?? 0].push(t);
  return { layers, cyclic, missingDeps };
}

export function DependencyGraph({ tasks }: { tasks: TaskStatus[] }) {
  if (tasks.length === 0) {
    return <div className="empty-state">タスクがありません</div>;
  }
  const { layers, cyclic, missingDeps } = computeLayers(tasks);
  return (
    <div className="dag-wrap">
      {(cyclic.size > 0 || missingDeps.size > 0) && (
        <div className="empty-state" style={{ color: "var(--danger)", marginBottom: 10 }}>
          ⚠ 依存関係に欠陥があります。該当タスクは実行可能にならず、ミッションが進まない可能性があります。
          {cyclic.size > 0 && <div>循環依存: {[...cyclic].join(", ")}</div>}
          {[...missingDeps.entries()].map(([id, deps]) => (
            <div key={id}>{id} が存在しないタスクに依存: {deps.join(", ")}</div>
          ))}
        </div>
      )}
      <div className="dag">
      {layers.map((layer, i) => (
        <div className="dag-layer" key={i}>
          <div className="dag-layer-label">Layer {i}</div>
          {layer.map((t) => (
            <div
              className="dag-node"
              key={t.id}
              style={
                cyclic.has(t.id) || missingDeps.has(t.id)
                  ? { outline: "1px solid var(--danger)" }
                  : undefined
              }
            >
              <div className="dag-node-id">{t.id}</div>
              <div className="dag-node-title">{t.title}</div>
              <StatusBadge status={t.status} />
              {t.deps.length > 0 && (
                <div className="dag-node-deps" style={{ marginTop: 8 }}>
                  {t.deps.map((d) => (
                    <span
                      className="dep-chip"
                      key={d}
                      style={missingDeps.get(t.id)?.includes(d) ? { color: "var(--danger)" } : undefined}
                    >
                      ← {d}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      ))}
      </div>
    </div>
  );
}
