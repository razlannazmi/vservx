/** A small router over the History API: real paths, so refresh, back and shared links work. */

export type Route =
  | { name: "sign-in" }
  | { name: "sign-up" }
  | { name: "home" }
  | { name: "servers"; workspaceSlug: string; serverId: number | null; instance: string | null }
  | { name: "keys" | "members" | "settings"; workspaceSlug: string }
  | { name: "admin-accounts" }
  | { name: "admin-workspaces" }
  | { name: "admin-database" }
  | { name: "account" }
  | { name: "not-found" };

const FIXED: Record<string, Route> = {
  "/sign-in": { name: "sign-in" },
  "/sign-up": { name: "sign-up" },
  "/": { name: "home" },
  "/workspaces": { name: "home" },
  "/admin/accounts": { name: "admin-accounts" },
  "/admin/workspaces": { name: "admin-workspaces" },
  "/admin/database": { name: "admin-database" },
  "/account": { name: "account" },
};

const WORKSPACE_PAGES = new Set(["keys", "members", "settings"]);

function id(text: string): number | null {
  return /^[1-9]\d*$/.test(text) ? Number(text) : null;
}

function decoded(text: string): string | null {
  try {
    return decodeURIComponent(text);
  } catch {
    return null; // A malformed escape: no such page.
  }
}

export function matchRoute(path: string): Route {
  const trimmed = path.length > 1 ? path.replace(/\/+$/, "") : path;
  const fixed = FIXED[trimmed];
  if (fixed) return fixed;

  // Which workspace a slug names depends on the list, so App resolves it.
  const [, first, workspaceSlug, page, server, sub, name, ...rest] = trimmed.split("/");
  if (first !== "workspaces" || !workspaceSlug || rest.length > 0) return { name: "not-found" };
  if (page === undefined || (page === "servers" && server === undefined)) {
    return { name: "servers", workspaceSlug, serverId: null, instance: null };
  }
  if (page === "servers" && server !== undefined) {
    const serverId = id(server);
    if (serverId === null) return { name: "not-found" };
    if (sub === undefined) return { name: "servers", workspaceSlug, serverId, instance: null };
    // An instance is its container's name, within the server.
    const instance = sub === "instances" && name ? decoded(name) : null;
    return instance ? { name: "servers", workspaceSlug, serverId, instance } : { name: "not-found" };
  }
  if (sub !== undefined) return { name: "not-found" };
  if (server === undefined && WORKSPACE_PAGES.has(page)) {
    return { name: page as "keys" | "members" | "settings", workspaceSlug };
  }
  return { name: "not-found" };
}

export function pathFor(route: Route): string {
  switch (route.name) {
    case "servers":
      if (route.serverId === null) return `/workspaces/${route.workspaceSlug}`;
      return route.instance === null
        ? `/workspaces/${route.workspaceSlug}/servers/${route.serverId}`
        : `/workspaces/${route.workspaceSlug}/servers/${route.serverId}/instances/${encodeURIComponent(route.instance)}`;
    case "keys":
    case "members":
    case "settings":
      return `/workspaces/${route.workspaceSlug}/${route.name}`;
    case "home":
      return "/";
    case "not-found":
      return "/";
    case "admin-accounts":
      return "/admin/accounts";
    case "admin-workspaces":
      return "/admin/workspaces";
    case "admin-database":
      return "/admin/database";
    default:
      return `/${route.name}`;
  }
}

export const router = $state<{ route: Route; path: string }>({
  route: matchRoute(location.pathname),
  path: location.pathname,
});

export function navigate(path: string, options: { replace?: boolean } = {}): void {
  if (path !== location.pathname) {
    if (options.replace) history.replaceState(null, "", path);
    else history.pushState(null, "", path);
  }
  router.path = path;
  router.route = matchRoute(path);
}

addEventListener("popstate", () => {
  router.path = location.pathname;
  router.route = matchRoute(location.pathname);
});

/** onclick for in-app <a href> links: plain left clicks stay in the page, anything else
 * (new tab, modifier keys) is left to the browser. */
export function followLink(event: MouseEvent): void {
  const link = event.currentTarget as HTMLAnchorElement;
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
    return;
  }
  if (link.target && link.target !== "_self") return;
  event.preventDefault();
  navigate(link.pathname);
}
