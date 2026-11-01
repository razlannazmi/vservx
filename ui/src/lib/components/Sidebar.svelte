<script lang="ts">
  import LogOutIcon from "@lucide/svelte/icons/log-out";
  import MoonIcon from "@lucide/svelte/icons/moon";
  import PlusIcon from "@lucide/svelte/icons/plus";
  import SunIcon from "@lucide/svelte/icons/sun";
  import UserIcon from "@lucide/svelte/icons/user";
  import { mode, toggleMode } from "mode-watcher";
  import { slide } from "svelte/transition";
  import { admin, loadPendingSignups } from "$lib/admin.svelte";
  import type { WorkspaceRead } from "$lib/api/client";
  import NewWorkspaceDialog from "$lib/components/NewWorkspaceDialog.svelte";
  import { duration } from "$lib/motion";
  import { isOwner } from "$lib/permissions";
  import { followLink, router } from "$lib/router.svelte";
  import { session, signOut } from "$lib/session.svelte";
  import { workspaces } from "$lib/workspaces.svelte";

  let creating = $state(false);

  const isAdmin = $derived(session.user?.role === "admin");
  const route = $derived(router.route);
  const currentWorkspace = $derived("workspaceId" in route ? route.workspaceId : null);

  $effect(() => {
    if (isAdmin) void loadPendingSignups();
  });

  function pagesOf(workspace: WorkspaceRead) {
    const pages = [
      { name: "servers", label: "Servers", href: `/w/${workspace.id}` },
      { name: "keys", label: "Keys", href: `/w/${workspace.id}/keys` },
      { name: "members", label: "Members", href: `/w/${workspace.id}/members` },
    ];
    if (isOwner(workspace.role)) pages.push({ name: "settings", label: "Settings", href: `/w/${workspace.id}/settings` });
    return pages;
  }

  // The current page is marked with weight, never colour.
  function itemClass(active: boolean): string {
    return `flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left outline-none hover:bg-sidebar-accent
      focus-visible:ring-2 focus-visible:ring-sidebar-ring ${active ? "font-semibold text-sidebar-foreground" : "text-muted-foreground hover:text-sidebar-foreground"}`;
  }
</script>

<nav aria-label="Main" class="flex h-full w-60 shrink-0 flex-col gap-6 overflow-y-auto border-r bg-sidebar px-3 py-4 text-sm">
  <a href="/" onclick={followLink} class="rounded-md px-2 font-mono text-base font-semibold outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring">
    vservx
  </a>

  <section class="space-y-1" aria-labelledby="sidebar-workspaces">
    <h2 id="sidebar-workspaces" class="px-2 pb-1 text-xs font-medium text-muted-foreground">Workspaces</h2>
    <ul class="space-y-0.5">
      {#each workspaces.list as workspace (workspace.id)}
        {@const open = workspace.id === currentWorkspace}
        <li>
          <a href={`/w/${workspace.id}`} onclick={followLink} class={itemClass(open)}>
            <span class="truncate">{workspace.name}</span>
          </a>
          {#if open}
            <ul class="mt-0.5 ml-3 space-y-0.5 border-l pl-2" transition:slide={{ duration: duration(200) }}>
              {#each pagesOf(workspace) as page (page.name)}
                {@const active = route.name === page.name}
                <li>
                  <a href={page.href} onclick={followLink} class={itemClass(active)} aria-current={active ? "page" : undefined}>
                    {page.label}
                  </a>
                </li>
              {/each}
            </ul>
          {/if}
        </li>
      {/each}
    </ul>
    <button type="button" class={itemClass(false)} onclick={() => (creating = true)}>
      <PlusIcon class="size-4" /> New workspace
    </button>
  </section>

  {#if isAdmin}
    <section class="space-y-1" aria-labelledby="sidebar-admin">
      <h2 id="sidebar-admin" class="px-2 pb-1 text-xs font-medium text-muted-foreground">Admin</h2>
      <a href="/admin/accounts" onclick={followLink} class={itemClass(route.name === "admin-accounts")}
         aria-current={route.name === "admin-accounts" ? "page" : undefined}>
        <span class="flex-1">Accounts</span>
        {#if admin.pendingSignups > 0}
          <span class="flex items-center gap-1.5 text-xs font-medium text-sidebar-foreground">
            <span class="size-2 rounded-full bg-status-warn" aria-hidden="true"></span>
            {admin.pendingSignups} waiting
          </span>
        {/if}
      </a>
      <a href="/admin/workspaces" onclick={followLink} class={itemClass(route.name === "admin-workspaces")}
         aria-current={route.name === "admin-workspaces" ? "page" : undefined}>Workspaces</a>
      <a href="/admin/database" onclick={followLink} class={itemClass(route.name === "admin-database")}
         aria-current={route.name === "admin-database" ? "page" : undefined}>Database</a>
    </section>
  {/if}

  <section class="mt-auto space-y-1" aria-labelledby="sidebar-you">
    <h2 id="sidebar-you" class="px-2 pb-1 text-xs font-medium text-muted-foreground">You</h2>
    <a href="/account" onclick={followLink} class={itemClass(route.name === "account")}
       aria-current={route.name === "account" ? "page" : undefined}>
      <UserIcon class="size-4" /> <span class="truncate">{session.user?.name ?? "Account"}</span>
    </a>
    <button type="button" class={itemClass(false)} onclick={toggleMode}>
      {#if mode.current === "dark"}
        <SunIcon class="size-4" /> Light mode
      {:else}
        <MoonIcon class="size-4" /> Dark mode
      {/if}
    </button>
    <button type="button" class={itemClass(false)} onclick={signOut}>
      <LogOutIcon class="size-4" /> Sign out
    </button>
  </section>
</nav>

<NewWorkspaceDialog bind:open={creating} />
