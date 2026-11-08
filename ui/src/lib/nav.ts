/** Where the app's navigation leads, shared by the sidebar and the phone tabs so the two never drift. */

import { isOwner } from "$lib/permissions";
import type { Route } from "$lib/router.svelte";
import type { Workspace } from "$lib/workspaces.svelte";

export type WorkspacePageName = "servers" | "keys" | "members" | "settings";
export type WorkspacePage = { name: WorkspacePageName; label: string; href: string };

/** A workspace's pages, in order. Settings is the owner's alone. */
export function workspacePages(workspace: Pick<Workspace, "slug" | "role">): WorkspacePage[] {
  const base = `/workspaces/${workspace.slug}`;
  const pages: WorkspacePage[] = [
    { name: "servers", label: "Servers", href: base },
    { name: "keys", label: "Keys", href: `${base}/keys` },
    { name: "members", label: "Members", href: `${base}/members` },
  ];
  if (isOwner(workspace.role)) pages.push({ name: "settings", label: "Settings", href: `${base}/settings` });
  return pages;
}

export type SystemPage = { name: "admin-accounts" | "admin-workspaces" | "admin-database"; label: string; href: string };

/** What covers all of vservx rather than one workspace: admins only. */
export const SYSTEM_PAGES: SystemPage[] = [
  { name: "admin-accounts", label: "Accounts", href: "/admin/accounts" },
  { name: "admin-workspaces", label: "Workspaces", href: "/admin/workspaces" },
  { name: "admin-database", label: "Database", href: "/admin/database" },
];

/** The workspace the phone tabs lead into: the one on screen, else the last one visited (by id, so a
 * rename keeps it), else the first. */
export function tabTarget(route: Route, list: Workspace[], lastId: number | null): Workspace | null {
  const shown = "workspaceSlug" in route ? list.find((each) => each.slug === route.workspaceSlug) : undefined;
  return shown ?? list.find((each) => each.id === lastId) ?? list[0] ?? null;
}

export type Tab = WorkspacePageName | "you";

/** The tab a route belongs to. Your account and the admin pages sit under "you"; the overview under none. */
export function activeTab(route: Route): Tab | null {
  switch (route.name) {
    case "servers":
    case "keys":
    case "members":
    case "settings":
      return route.name;
    case "account":
    case "admin-accounts":
    case "admin-workspaces":
    case "admin-database":
      return "you";
    default:
      return null;
  }
}
