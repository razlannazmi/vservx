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

/** What each role covers, for the table on the Members page. Matches the checks the API makes. */
export const ROLE_COVERAGE: { label: string; roles: WorkspaceRole[] }[] = [
  { label: "See servers, keys and members", roles: ["viewer", "operator", "owner"] },
  { label: "Test connections", roles: ["viewer", "operator", "owner"] },
  { label: "Add, edit and delete servers", roles: ["operator", "owner"] },
  { label: "Add, replace and delete saved keys", roles: ["operator", "owner"] },
  { label: "Accept a changed host key", roles: ["operator", "owner"] },
  { label: "Add and remove members, change their roles", roles: ["owner"] },
  { label: "Rename, hand over or delete the workspace", roles: ["owner"] },
  // The owner hands the workspace over first.
  { label: "Leave the workspace", roles: ["viewer", "operator"] },
];

export const ROLE_HELP: Record<WorkspaceRole, string> = {
  viewer: "Sees the servers, keys and members, and tests connections.",
  operator: "Also adds, edits and deletes servers and keys, and accepts changed host keys.",
  owner: "Also manages members, and renames, hands over or deletes the workspace.",
};
