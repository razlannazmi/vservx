<script lang="ts">
  import ChevronDownIcon from "@lucide/svelte/icons/chevron-down";
  import LayersIcon from "@lucide/svelte/icons/layers";
  import LogOutIcon from "@lucide/svelte/icons/log-out";
  import MoonIcon from "@lucide/svelte/icons/moon";
  import PanelLeftCloseIcon from "@lucide/svelte/icons/panel-left-close";
  import PanelLeftOpenIcon from "@lucide/svelte/icons/panel-left-open";
  import PlusIcon from "@lucide/svelte/icons/plus";
  import SettingsIcon from "@lucide/svelte/icons/settings";
  import SunIcon from "@lucide/svelte/icons/sun";
  import UserIcon from "@lucide/svelte/icons/user";
  import { mode, toggleMode } from "mode-watcher";
  import { fade, fly, slide } from "svelte/transition";
  import { admin } from "$lib/admin.svelte";
  import NewWorkspaceDialog from "$lib/components/NewWorkspaceDialog.svelte";
  import RailItem, { RAIL_POPUP_OFFSET, railClass } from "$lib/components/RailItem.svelte";
  import SignOutDialog from "$lib/components/SignOutDialog.svelte";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import WorkspaceIcon from "$lib/components/WorkspaceIcon.svelte";
  import { duration, easeOut } from "$lib/motion";
  import { SYSTEM_PAGES, workspacePages } from "$lib/nav";
  import { PAGE_ICONS } from "$lib/nav-icons";
  import { followLink, navigate, router } from "$lib/router.svelte";
  import { session } from "$lib/session.svelte";
  import { workspaces } from "$lib/workspaces.svelte";

  type Section = "workspaces" | "system";

  // Folded sections and the collapsed sidebar stay that way across reloads, in this browser only.
  const FOLDED_KEY = "vservx.sidebar.folded";
  const COLLAPSED_KEY = "vservx.sidebar.collapsed";

  let creating = $state(false);
  let confirmSignOut = $state(false);
  // The workspace row under the pointer or focus: its icon plays.
  let hovered = $state<number | null>(null);
  let folded = $state<Record<Section, boolean>>({ workspaces: false, system: false, ...readStored(FOLDED_KEY, {}) });
  let collapsed = $state(readStored<unknown>(COLLAPSED_KEY, false) === true);

  const isAdmin = $derived(session.user?.role === "admin");
  const route = $derived(router.route);
  const currentWorkspace = $derived("workspaceSlug" in route ? route.workspaceSlug : null);
  const modeLabel = $derived(mode.current === "dark" ? "Switch to light mode" : "Switch to dark mode");
  const waiting = $derived(isAdmin && admin.pendingSignups > 0);
  const onSystemPage = $derived(SYSTEM_PAGES.some((page) => page.name === route.name));

  function readStored<T>(key: string, fallback: T): T {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  }

  function store(key: string, value: unknown) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Storage can be refused (private windows); folding and collapsing still work until a reload.
    }
  }

  function toggle(section: Section) {
    folded[section] = !folded[section];
    store(FOLDED_KEY, folded);
  }

  function toggleCollapsed() {
    collapsed = !collapsed;
    store(COLLAPSED_KEY, collapsed);
  }

  // Section headings sit a size up from their links, in full weight, so they never read as one more link.
  const headingClass = `group flex w-full items-center gap-2 rounded-md px-2 py-1 text-sm font-semibold
    text-sidebar-foreground outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring`;

  // The current page is marked with weight, never colour.
  function itemClass(active: boolean): string {
    return `flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left outline-none hover:bg-sidebar-accent
      focus-visible:ring-2 focus-visible:ring-sidebar-ring ${active ? "font-semibold text-sidebar-foreground" : "text-sidebar-foreground/75 hover:text-sidebar-foreground"}`;
  }

  const iconButtonClass = `relative grid size-8 shrink-0 place-items-center rounded-md text-sidebar-foreground/75 outline-none
    hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring`;
</script>

{#snippet heading(section: Section, label: string, Icon: typeof LayersIcon, waiting: boolean)}
  <h2 id={`sidebar-${section}`}>
    <button type="button" class={headingClass} onclick={() => toggle(section)}
            aria-expanded={!folded[section]} aria-controls={`sidebar-${section}-items`}>
      <Icon class="size-4" />
      <span class="flex-1 text-left">{label}</span>
      {#if waiting}
        <span class="size-2 rounded-full bg-status-warn" aria-hidden="true"></span>
        <span class="sr-only">(accounts waiting for approval)</span>
      {/if}
      <ChevronDownIcon class={`size-4 text-muted-foreground transition-[rotate,color] duration-200 ease-out
        group-hover:text-sidebar-foreground ${folded[section] ? "-rotate-90" : ""}`} />
    </button>
  </h2>
{/snippet}

<!-- Shows the mode a click switches to; the icons turn as they trade places. -->
{#snippet modeIcons()}
  <MoonIcon class="size-4 transition-[scale,rotate,opacity] duration-200 ease-out dark:scale-90 dark:-rotate-90 dark:opacity-0" />
  <SunIcon class="absolute size-4 scale-90 rotate-90 opacity-0 transition-[scale,rotate,opacity] duration-200 ease-out dark:scale-100 dark:rotate-0 dark:opacity-100" />
{/snippet}

<!-- Collapsing and expanding:
     - The width eases out, so the sidebar answers the click at once.
     - Each layout is pinned to the left at its own fixed width, so the full one is revealed rather than
       reflowed as the sidebar opens.
     - The leaving layout fades out fast while the arriving one fades in a beat later, nudged in from the
       left; icons sit 20px from the edge in both, so they hold still through the swap. -->
<Tooltip.Provider delayDuration={200}>
  <nav aria-label="Main"
       class={`relative hidden h-full shrink-0 overflow-hidden border-r bg-sidebar text-xs transition-[width] duration-250
         ease-out motion-reduce:transition-none md:block ${collapsed ? "w-14" : "w-60"}`}>
    {#if collapsed}
      <div class="absolute inset-y-0 left-0 flex w-14 flex-col gap-4 px-2.5 py-4"
           in:fly={{ x: -6, duration: duration(200), delay: duration(60), easing: easeOut }}
           out:fade={{ duration: duration(100), easing: easeOut }}>
        <div class="flex h-9 shrink-0 items-center">
          <RailItem label="Expand sidebar" onclick={toggleCollapsed} aria-expanded={false}>
            <PanelLeftOpenIcon class="size-4" />
          </RailItem>
        </div>

        <!-- Only the workspace list scrolls. The inset keeps focus rings inside the scroll box. -->
        <section class="-m-1 flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto p-1" aria-label="Workspaces">
          <RailItem label="All workspaces" href="/" active={route.name === "home"}>
            <LayersIcon class="size-4" />
          </RailItem>
          <ul class="flex flex-col gap-1">
            {#each workspaces.list as workspace (workspace.id)}
              {@const open = workspace.slug === currentWorkspace}
              <!-- The open workspace and its pages share one tinted column, like the indented list when expanded. -->
              <li class={open ? "flex flex-col gap-0.5 rounded-md bg-sidebar-accent/40" : ""}>
                <RailItem label={workspace.name} href={`/workspaces/${workspace.slug}`}
                          onpointerenter={() => (hovered = workspace.id)} onpointerleave={() => (hovered = null)}
                          onfocus={() => (hovered = workspace.id)} onblur={() => (hovered = null)}>
                  <WorkspaceIcon name={workspace.icon} size={16} animate={hovered === workspace.id} />
                </RailItem>
                {#if open}
                  {#each workspacePages(workspace) as page (page.name)}
                    {@const Icon = PAGE_ICONS[page.name]}
                    <RailItem label={page.label} href={page.href} active={route.name === page.name}>
                      <Icon class="size-4" />
                    </RailItem>
                  {/each}
                {/if}
              </li>
            {/each}
          </ul>
          <RailItem label="New workspace" onclick={() => (creating = true)}>
            <PlusIcon class="size-4" />
          </RailItem>
        </section>

        <div class="flex shrink-0 flex-col gap-4">
          {#if isAdmin}
            <!-- One icon opens the System pages; its dot shows when accounts wait for approval. -->
            <DropdownMenu.Root>
              <DropdownMenu.Trigger class={railClass(onSystemPage)}
                                    aria-label={waiting ? "System (accounts waiting for approval)" : "System"}>
                <SettingsIcon class="size-4" />
                {#if waiting}
                  <span class="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-status-warn" aria-hidden="true"></span>
                {/if}
              </DropdownMenu.Trigger>
              <DropdownMenu.Content side="right" align="end" sideOffset={RAIL_POPUP_OFFSET} class="w-52">
                <DropdownMenu.Label>System</DropdownMenu.Label>
                {#each SYSTEM_PAGES as page (page.name)}
                  <DropdownMenu.Item class={route.name === page.name ? "font-semibold" : ""} onSelect={() => navigate(page.href)}>
                    <span class="flex-1">{page.label}</span>
                    {#if page.name === "admin-accounts" && admin.pendingSignups > 0}
                      <span class="flex items-center gap-1.5 text-xs font-medium">
                        <span class="size-2 rounded-full bg-status-warn" aria-hidden="true"></span>
                        {admin.pendingSignups} waiting
                      </span>
                    {/if}
                  </DropdownMenu.Item>
                {/each}
              </DropdownMenu.Content>
            </DropdownMenu.Root>
          {/if}

          <section class="flex flex-col gap-1 border-t pt-3" aria-label="You">
            <RailItem label={session.user?.name ?? "Account"} href="/account" active={route.name === "account"}>
              <UserIcon class="size-4" />
            </RailItem>
            <RailItem label={modeLabel} onclick={toggleMode}>
              {@render modeIcons()}
            </RailItem>
            <RailItem label="Sign out" onclick={() => (confirmSignOut = true)}>
              <LogOutIcon class="size-4" />
            </RailItem>
          </section>
        </div>
      </div>
    {:else}
      <div class="absolute inset-y-0 left-0 flex w-60 flex-col gap-6 px-3 py-4"
           in:fly={{ x: -6, duration: duration(200), delay: duration(60), easing: easeOut }}
           out:fade={{ duration: duration(100), easing: easeOut }}>
        <div class="flex h-9 shrink-0 items-center justify-between">
          <a href="/" onclick={followLink} class="rounded-md px-2 font-mono text-base font-semibold outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring">
            vservx
          </a>
          <button type="button" class={iconButtonClass} onclick={toggleCollapsed}
                  aria-label="Collapse sidebar" title="Collapse sidebar" aria-expanded={true}>
            <PanelLeftCloseIcon class="size-4" />
          </button>
        </div>

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
              {@render heading("system", "System", SettingsIcon, folded.system && waiting)}
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
              <button type="button" onclick={toggleMode} aria-label={modeLabel} title={modeLabel} class={iconButtonClass}>
                {@render modeIcons()}
              </button>
            </div>
            <button type="button" class={itemClass(false)} onclick={() => (confirmSignOut = true)}>
              <LogOutIcon class="size-4" /> Sign out
            </button>
          </section>
        </div>
      </div>
    {/if}
  </nav>
</Tooltip.Provider>

<NewWorkspaceDialog bind:open={creating} />
<SignOutDialog bind:open={confirmSignOut} />
