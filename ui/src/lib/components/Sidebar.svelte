<script lang="ts">
  import ChevronDownIcon from "@lucide/svelte/icons/chevron-down";
  import LayersIcon from "@lucide/svelte/icons/layers";
  import LogOutIcon from "@lucide/svelte/icons/log-out";
  import MoonIcon from "@lucide/svelte/icons/moon";
  import PlusIcon from "@lucide/svelte/icons/plus";
  import SettingsIcon from "@lucide/svelte/icons/settings";
  import SunIcon from "@lucide/svelte/icons/sun";
  import UserIcon from "@lucide/svelte/icons/user";
  import { mode, toggleMode } from "mode-watcher";
  import { slide } from "svelte/transition";
  import { admin } from "$lib/admin.svelte";
  import NewWorkspaceDialog from "$lib/components/NewWorkspaceDialog.svelte";
  import SignOutDialog from "$lib/components/SignOutDialog.svelte";
  import WorkspaceIcon from "$lib/components/WorkspaceIcon.svelte";
  import { duration, easeOut } from "$lib/motion";
  import { SYSTEM_PAGES, workspacePages } from "$lib/nav";
  import { followLink, router } from "$lib/router.svelte";
  import { session } from "$lib/session.svelte";
  import { workspaces } from "$lib/workspaces.svelte";

  type Section = "workspaces" | "system";

  // Folded sections stay folded across reloads, in this browser only.
  const FOLDED_KEY = "vservx.sidebar.folded";

  let creating = $state(false);
  let confirmSignOut = $state(false);
  // The workspace row under the pointer or focus: its icon plays.
  let hovered = $state<number | null>(null);
  let folded = $state<Record<Section, boolean>>({ workspaces: false, system: false, ...readFolded() });

  const isAdmin = $derived(session.user?.role === "admin");
  const route = $derived(router.route);
  const currentWorkspace = $derived("workspaceSlug" in route ? route.workspaceSlug : null);
  const modeLabel = $derived(mode.current === "dark" ? "Switch to light mode" : "Switch to dark mode");

  function readFolded(): Partial<Record<Section, boolean>> {
    try {
      return JSON.parse(localStorage.getItem(FOLDED_KEY) ?? "{}");
    } catch {
      return {};
    }
  }

  function toggle(section: Section) {
    folded[section] = !folded[section];
    try {
      localStorage.setItem(FOLDED_KEY, JSON.stringify(folded));
    } catch {
      // Storage can be refused (private windows); folding still works until a reload.
    }
  }

  // Section headings are small capitals with an icon, so they never read as one more link.
  const headingClass = `flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-medium tracking-wider
    text-muted-foreground uppercase outline-none hover:text-sidebar-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring`;

  // The current page is marked with weight, never colour.
  function itemClass(active: boolean): string {
    return `flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left outline-none hover:bg-sidebar-accent
      focus-visible:ring-2 focus-visible:ring-sidebar-ring ${active ? "font-semibold text-sidebar-foreground" : "text-sidebar-foreground/75 hover:text-sidebar-foreground"}`;
  }
</script>

{#snippet heading(section: Section, label: string, Icon: typeof LayersIcon, waiting: boolean)}
  <h2 id={`sidebar-${section}`}>
    <button type="button" class={headingClass} onclick={() => toggle(section)}
            aria-expanded={!folded[section]} aria-controls={`sidebar-${section}-items`}>
      <Icon class="size-3.5" />
      <span class="flex-1 text-left">{label}</span>
      {#if waiting}
        <span class="size-2 rounded-full bg-status-warn" aria-hidden="true"></span>
        <span class="sr-only">(accounts waiting for approval)</span>
      {/if}
      <ChevronDownIcon class={`size-3.5 transition-transform duration-200 ease-out ${folded[section] ? "-rotate-90" : ""}`} />
    </button>
  </h2>
{/snippet}

<nav aria-label="Main" class="hidden h-full w-60 shrink-0 md:flex flex-col gap-6 border-r bg-sidebar px-3 py-4 text-sm">
  <a href="/" onclick={followLink} class="shrink-0 rounded-md px-2 font-mono text-base font-semibold outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring">
    vservx
  </a>

  <!-- Only the workspace list scrolls; System and your account stay at the bottom. The inset keeps
       focus rings inside the scroll box. -->
  <section class="-m-1 min-h-0 flex-1 space-y-1 overflow-y-auto p-1" aria-labelledby="sidebar-workspaces">
    {@render heading("workspaces", "Workspaces", LayersIcon, false)}
    {#if !folded.workspaces}
      <div id="sidebar-workspaces-items" class="space-y-1" transition:slide={{ duration: duration(200), easing: easeOut }}>
        <ul class="space-y-0.5">
          {#each workspaces.list as workspace (workspace.id)}
            {@const open = workspace.slug === currentWorkspace}
            <li>
              <a href={`/workspaces/${workspace.slug}`} onclick={followLink} class={itemClass(open)}
                 onpointerenter={() => (hovered = workspace.id)} onpointerleave={() => (hovered = null)}
                 onfocus={() => (hovered = workspace.id)} onblur={() => (hovered = null)}>
                <WorkspaceIcon name={workspace.icon} size={16} animate={hovered === workspace.id} />
                <span class="truncate">{workspace.name}</span>
              </a>
              {#if open}
                <ul class="mt-0.5 ml-3 space-y-0.5 border-l pl-2" transition:slide={{ duration: duration(200), easing: easeOut }}>
                  {#each workspacePages(workspace) as page (page.name)}
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
      </div>
    {/if}
  </section>

  <div class="flex shrink-0 flex-col gap-6">
    {#if isAdmin}
      <!-- Admins only: what covers all of vservx rather than one workspace. Folded, the heading
           still shows when accounts wait for approval. -->
      <section class="space-y-1" aria-labelledby="sidebar-system">
        {@render heading("system", "System", SettingsIcon, folded.system && admin.pendingSignups > 0)}
        {#if !folded.system}
          <div id="sidebar-system-items" class="space-y-1" transition:slide={{ duration: duration(200), easing: easeOut }}>
            {#each SYSTEM_PAGES as page (page.name)}
              <a href={page.href} onclick={followLink} class={itemClass(route.name === page.name)}
                 aria-current={route.name === page.name ? "page" : undefined}>
                {#if page.name === "admin-accounts"}
                  <span class="flex-1">{page.label}</span>
                  {#if admin.pendingSignups > 0}
                    <span class="flex items-center gap-1.5 text-xs font-medium text-sidebar-foreground">
                      <span class="size-2 rounded-full bg-status-warn" aria-hidden="true"></span>
                      {admin.pendingSignups} waiting
                    </span>
                  {/if}
                {:else}
                  {page.label}
                {/if}
              </a>
            {/each}
          </div>
        {/if}
      </section>
    {/if}

    <!-- Your own things sit apart at the very bottom; your name says whose they are. -->
    <section class="space-y-0.5 border-t pt-3" aria-label="You">
      <div class="flex items-center gap-1">
        <a href="/account" onclick={followLink} class={`${itemClass(route.name === "account")} min-w-0`}
           aria-current={route.name === "account" ? "page" : undefined}>
          <UserIcon class="size-4 shrink-0" /> <span class="truncate">{session.user?.name ?? "Account"}</span>
        </a>
        <!-- Shows the mode a click switches to; the icons turn as they trade places. -->
        <button type="button" onclick={toggleMode} aria-label={modeLabel} title={modeLabel}
                class="relative grid size-8 shrink-0 place-items-center rounded-md text-sidebar-foreground/75 outline-none
                  hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring">
          <MoonIcon class="size-4 transition-[scale,rotate,opacity] duration-200 ease-out dark:scale-90 dark:-rotate-90 dark:opacity-0" />
          <SunIcon class="absolute size-4 scale-90 rotate-90 opacity-0 transition-[scale,rotate,opacity] duration-200 ease-out dark:scale-100 dark:rotate-0 dark:opacity-100" />
        </button>
      </div>
      <button type="button" class={itemClass(false)} onclick={() => (confirmSignOut = true)}>
        <LogOutIcon class="size-4" /> Sign out
      </button>
    </section>
  </div>
</nav>

<NewWorkspaceDialog bind:open={creating} />
<SignOutDialog bind:open={confirmSignOut} />
