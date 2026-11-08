<script lang="ts">
  import CircleUserIcon from "@lucide/svelte/icons/circle-user";
  import KeyRoundIcon from "@lucide/svelte/icons/key-round";
  import ServerIcon from "@lucide/svelte/icons/server";
  import SettingsIcon from "@lucide/svelte/icons/settings";
  import UsersIcon from "@lucide/svelte/icons/users";
  import { admin } from "$lib/admin.svelte";
  import YouPanel from "$lib/components/YouPanel.svelte";
  import { activeTab, tabTarget, workspacePages, type WorkspacePageName } from "$lib/nav";
  import { followLink, router } from "$lib/router.svelte";
  import { session } from "$lib/session.svelte";
  import { workspaces } from "$lib/workspaces.svelte";

  // Phones only: one workspace's pages under the thumb, then You. Off a workspace page they lead into
  // the last one visited; with no workspaces, only You.
  let youOpen = $state(false);

  const ICONS: Record<WorkspacePageName, typeof ServerIcon> = {
    servers: ServerIcon,
    keys: KeyRoundIcon,
    members: UsersIcon,
    settings: SettingsIcon,
  };

  const route = $derived(router.route);
  const target = $derived(tabTarget(route, workspaces.list, workspaces.lastId));
  const active = $derived(activeTab(route));
  const waiting = $derived(session.user?.role === "admin" && admin.pendingSignups > 0);

  // The current tab is marked with weight, never colour.
  function tabClass(on: boolean): string {
    return `relative flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] outline-none
      focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sidebar-ring
      ${on ? "font-semibold text-sidebar-foreground" : "text-muted-foreground"}`;
  }
</script>

<nav aria-label="Main" class="shrink-0 border-t bg-sidebar pb-[env(safe-area-inset-bottom)]">
  <div class="flex h-14">
    {#if target}
      {#each workspacePages(target) as page (page.name)}
        {@const Icon = ICONS[page.name]}
        {@const on = active === page.name}
        <a href={page.href} onclick={followLink} class={tabClass(on)} aria-current={on ? "page" : undefined}>
          <Icon class="size-5" aria-hidden="true" />
          <span class="truncate">{page.label}</span>
        </a>
      {/each}
    {/if}
    <button type="button" class={tabClass(active === "you")} aria-current={active === "you" ? "page" : undefined}
            onclick={() => (youOpen = true)}>
      <span class="relative">
        <CircleUserIcon class="size-5" aria-hidden="true" />
        {#if waiting}
          <span class="absolute -top-0.5 -right-0.5 size-1.5 rounded-full bg-status-warn" aria-hidden="true"></span>
        {/if}
      </span>
      You
      {#if waiting}<span class="sr-only">(accounts waiting for approval)</span>{/if}
    </button>
  </div>
</nav>

<YouPanel bind:open={youOpen} />
