/** What each workspace role may do. Buttons a role can't use are hidden, not disabled. */

import type { WorkspaceRole } from "$lib/api/client";

/** Add, edit and delete servers and keys; accept changed host keys. */
export function canOperate(role: WorkspaceRole): boolean {
  return role === "operator" || role === "owner";
}

/** Manage members, rename, hand over or delete the workspace. */
export function isOwner(role: WorkspaceRole): boolean {
  return role === "owner";
}

export const ROLE_NAMES: Record<WorkspaceRole, string> = { viewer: "Viewer", operator: "Operator", owner: "Owner" };

export const ROLE_HELP: Record<WorkspaceRole, string> = {
  viewer: "Sees the servers, keys and members, and tests connections.",
  operator: "Also adds, edits and deletes servers and keys, and accepts changed host keys.",
  owner: "Also manages members, and renames, hands over or deletes the workspace.",
};
