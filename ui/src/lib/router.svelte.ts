/** A small router over the History API: real paths, so refresh, back and shared links work. */

import { isInstanceSource, type InstanceRef } from "$lib/watch";

export type Route =
  | { name: "sign-in" }
  | { name: "sign-up" }
  | { name: "home" }
  | { name: "servers"; workspaceSlug: string; serverId: number | null; instance: InstanceRef | null }
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

/** The part of an address that picks the page: its path, and an instance's ?source=. The rest of the
 * query (the snapshots drawer's) is the page's own. */
function pagePath(pathname: string, search: string): string {
  const source = new URLSearchParams(search).get("source");
  return source === null ? pathname : `${pathname}?source=${encodeURIComponent(source)}`;
}

/** An instance's address below its server's: its name, and its source unless it's Docker's. */
export function instancePath(instance: InstanceRef): string {
  const path = `instances/${encodeURIComponent(instance.name)}`;
  return instance.source === "docker" ? path : `${path}?source=${instance.source}`;
}

export function matchRoute(address: string): Route {
  const query = address.indexOf("?");
  const path = query < 0 ? address : address.slice(0, query);
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
    // An instance is its container's or unit's name within the server, and its ?source=. Without one
    // it's Docker's, as the API takes it and as every address from before systemd units meant.
    const instance = sub === "instances" && name ? decoded(name) : null;
    const source = new URLSearchParams(query < 0 ? "" : address.slice(query)).get("source") ?? "docker";
    return instance && isInstanceSource(source)
      ? { name: "servers", workspaceSlug, serverId, instance: { source, name: instance } }
      : { name: "not-found" };
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
        : `/workspaces/${route.workspaceSlug}/servers/${route.serverId}/${instancePath(route.instance)}`;
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

// `path` is the page's address: pagePath, not the drawer's query.
export const router = $state<{ route: Route; path: string }>({
  route: matchRoute(pagePath(location.pathname, location.search)),
  path: pagePath(location.pathname, location.search),
});

export function navigate(path: string, options: { replace?: boolean } = {}): void {
  if (path !== pagePath(location.pathname, location.search)) {
    if (options.replace) history.replaceState(null, "", path);
    else history.pushState(null, "", path);
  }
  router.path = path;
  router.route = matchRoute(path);
}

addEventListener("popstate", () => {
  router.path = pagePath(location.pathname, location.search);
  router.route = matchRoute(router.path);
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
  navigate(pagePath(link.pathname, link.search));
}
