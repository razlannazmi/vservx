/** The signed-in person's workspaces, with their role in each. */

import { api, errorMessage, type WorkspaceRead } from "$lib/api/client";
import { navigate, pathFor, router } from "$lib/router.svelte";
import { withSlugs } from "$lib/slug";

/** A workspace and its address in the app, made from its name. */
export type Workspace = WorkspaceRead & { slug: string };

export const workspaces = $state<{ list: Workspace[]; loaded: boolean }>({ list: [], loaded: false });

export async function loadWorkspaces(): Promise<void> {
  const { data } = await api.GET("/api/workspaces");
  const route = router.route;
  const shown = "workspaceSlug" in route ? workspaceBySlug(route.workspaceSlug) : null;
  workspaces.list = withSlugs(data ?? []);
  workspaces.loaded = true;
  // A rename gives the workspace on screen a new address: follow it, on the same page. In the
  // same tick as the new list, so the page never sees its old address go missing.
  const moved = shown && workspaces.list.find((each) => each.id === shown.id);
  if (moved && moved.slug !== shown.slug && "workspaceSlug" in route) {
    navigate(pathFor({ ...route, workspaceSlug: moved.slug }), { replace: true });
  }
}

/** Create a workspace (the caller owns it) and refresh the list. Throws with the API's words.
 * A null icon is the default, so it follows the default if that ever changes. */
export async function createWorkspace(name: string, icon: string | null = null): Promise<Workspace> {
  const { data, error } = await api.POST("/api/workspaces", { body: { name, icon } });
  if (error || !data) throw new Error(errorMessage(error, "Couldn't create the workspace"));
  await loadWorkspaces();
  // Its address depends on the names already taken.
  return workspaces.list.find((each) => each.id === data.id) ?? withSlugs([data])[0];
}

export function workspaceBySlug(slug: string): Workspace | null {
  return workspaces.list.find((workspace) => workspace.slug === slug) ?? null;
}

/** A workspace route said 404: it's gone, or the caller was removed. Start again from home. */
export async function leaveMissingWorkspace(): Promise<void> {
  await loadWorkspaces();
  navigate("/", { replace: true });
}
