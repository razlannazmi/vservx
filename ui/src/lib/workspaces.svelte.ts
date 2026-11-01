/** The signed-in person's workspaces, with their role in each. */

import { api, errorMessage, type WorkspaceRead } from "$lib/api/client";
import { navigate } from "$lib/router.svelte";

export const workspaces = $state<{ list: WorkspaceRead[]; loaded: boolean }>({ list: [], loaded: false });

export async function loadWorkspaces(): Promise<void> {
  const { data } = await api.GET("/api/workspaces");
  workspaces.list = data ?? [];
  workspaces.loaded = true;
}

/** Create a workspace (the caller owns it) and refresh the list. Throws with the API's words. */
export async function createWorkspace(name: string): Promise<WorkspaceRead> {
  const { data, error } = await api.POST("/api/workspaces", { body: { name } });
  if (error || !data) throw new Error(errorMessage(error, "Couldn't create the workspace"));
  await loadWorkspaces();
  return data;
}

export function workspaceById(id: number): WorkspaceRead | null {
  return workspaces.list.find((workspace) => workspace.id === id) ?? null;
}

/** A workspace route said 404: it's gone, or the caller was removed. Start again from home. */
export async function leaveMissingWorkspace(): Promise<void> {
  await loadWorkspaces();
  navigate("/", { replace: true });
}
