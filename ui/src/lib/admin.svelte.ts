/** What the sidebar shows app admins: how many sign-ups wait for approval. */

import { api } from "$lib/api/client";

export const admin = $state({ pendingSignups: 0 });

export async function loadPendingSignups(): Promise<void> {
  const { data } = await api.GET("/api/admin/accounts");
  admin.pendingSignups = (data ?? []).filter((account) => account.approved_at === null).length;
}
