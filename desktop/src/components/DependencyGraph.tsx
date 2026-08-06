import type { TaskStatus } from "../types";
import { StatusBadge } from "./StatusBadge";

// タスクの依存関係を「深さ」でレイヤ分けして左→右に並べる簡易DAG表示。
// 矢印は描かず、各カードの依存先IDをチップで示すことで依存が読み取れるようにする。
function computeLayers(tasks: TaskStatus[]): TaskStatus[][] {
  const byId = new Map(tasks.map((t) => [t.id, t]));
  const depth = new Map<string, number>();

  function depthOf(id: string, guard: Set<string>): number {
    if (depth.has(id)) return depth.get(id) as number;
    if (guard.has(id)) return 0; // 循環はここで打ち切る(通常発生しない想定)
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
  return layers;
}

export function DependencyGraph({ tasks }: { tasks: TaskStatus[] }) {
  if (tasks.length === 0) {
    return <div className="empty-state">タスクがありません</div>;
  }
  const layers = computeLayers(tasks);
  return (
    <div className="dag">
      {layers.map((layer, i) => (
        <div className="dag-layer" key={i}>
          <div className="dag-layer-label">Layer {i}</div>
          {layer.map((t) => (
            <div className="dag-node" key={t.id}>
              <div className="dag-node-id">{t.id}</div>
              <div className="dag-node-title">{t.title}</div>
              <StatusBadge status={t.status} />
              {t.deps.length > 0 && (
                <div className="dag-node-deps" style={{ marginTop: 8 }}>
                  {t.deps.map((d) => (
                    <span className="dep-chip" key={d}>← {d}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
