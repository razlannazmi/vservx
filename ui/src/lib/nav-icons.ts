/** Each workspace page's icon, shared by the phone tabs and the collapsed sidebar so the two never drift. */

import KeyRoundIcon from "@lucide/svelte/icons/key-round";
import ServerIcon from "@lucide/svelte/icons/server";
import SettingsIcon from "@lucide/svelte/icons/settings";
import UsersIcon from "@lucide/svelte/icons/users";
import type { WorkspacePageName } from "$lib/nav";

export const PAGE_ICONS: Record<WorkspacePageName, typeof ServerIcon> = {
  servers: ServerIcon,
  keys: KeyRoundIcon,
  members: UsersIcon,
  settings: SettingsIcon,
};
