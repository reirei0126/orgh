import { useEffect, useState } from "react";

// 軽量ルーティング: URLハッシュベースで #/ #/new #/settings #/report #/playbooks #/mission/:id を扱う。
// react-router等は使わず、外部依存を増やさない。

export type Route =
  | { name: "list" }
  | { name: "new" }
  | { name: "settings" }
  | { name: "report" }
  | { name: "playbooks"; missionId?: string }
  | { name: "mission"; missionId: string };

function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, "") || "/";
  const missionMatch = path.match(/^\/mission\/([^/]+)$/);
  if (missionMatch) return { name: "mission", missionId: decodeURIComponent(missionMatch[1]) };
  if (path === "/new") return { name: "new" };
  if (path === "/settings") return { name: "settings" };
  if (path === "/report") return { name: "report" };
  const playbooksMatch = path.match(/^\/playbooks\/([^/]+)$/);
  if (playbooksMatch) return { name: "playbooks", missionId: decodeURIComponent(playbooksMatch[1]) };
  if (path === "/playbooks") return { name: "playbooks" };
  return { name: "list" };
}

export function routeToHash(route: Route): string {
  switch (route.name) {
    case "list":
      return "#/";
    case "new":
      return "#/new";
    case "settings":
      return "#/settings";
    case "report":
      return "#/report";
    case "playbooks":
      return route.missionId ? `#/playbooks/${encodeURIComponent(route.missionId)}` : "#/playbooks";
    case "mission":
      return `#/mission/${encodeURIComponent(route.missionId)}`;
  }
}

export function useRoute(): [Route, (route: Route) => void] {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));

  useEffect(() => {
    const onHashChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = (next: Route) => {
    window.location.hash = routeToHash(next);
  };

  return [route, navigate];
}
