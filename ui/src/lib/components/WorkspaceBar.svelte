<script lang="ts">
  import ChevronUpIcon from "@lucide/svelte/icons/chevron-up";
  import LayersIcon from "@lucide/svelte/icons/layers";
  import PlusIcon from "@lucide/svelte/icons/plus";
  import { fade } from "svelte/transition";
  import NewWorkspaceDialog from "$lib/components/NewWorkspaceDialog.svelte";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import WorkspaceIcon from "$lib/components/WorkspaceIcon.svelte";
  import { duration, easeOut } from "$lib/motion";
  import { tabTarget } from "$lib/nav";
  import { navigate, router } from "$lib/router.svelte";
  import { workspaces } from "$lib/workspaces.svelte";

  // Phones only: a full-width bar just above the tabs, by the thumb, saying which workspace the tabs lead
  // into. It opens upward over a dimmed, blurred page so the choice is all there is to look at.
  let open = $state(false);
  let creating = $state(false);

  const route = $derived(router.route);
  const target = $derived(tabTarget(route, workspaces.list, workspaces.lastId));
  const inWorkspace = $derived("workspaceSlug" in route);
  const home = $derived(route.name === "home");
</script>

{#if open}
  <div
    class="fixed inset-0 z-40 bg-black/40 supports-backdrop-filter:backdrop-blur-xs"
    aria-hidden="true"
    transition:fade={{ duration: duration(150), easing: easeOut }}
  ></div>
{/if}

<div class="shrink-0 border-t bg-sidebar">
  <DropdownMenu.Root bind:open>
    <DropdownMenu.Trigger
      class="flex h-11 w-full min-w-0 items-center gap-2 px-4 text-left text-sm text-sidebar-foreground outline-none
             focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sidebar-ring"
      aria-label="Switch workspace"
    >
      {#if home}
        <LayersIcon class="size-4 shrink-0" />
        <span class="min-w-0 flex-1 truncate font-medium">Workspaces</span>
      {:else if target}
        <WorkspaceIcon name={target.icon} size={16} />
        <span class="min-w-0 flex-1 truncate font-medium">{target.name}</span>
      {:else}
        <span class="min-w-0 flex-1 truncate font-medium">Workspaces</span>
      {/if}
      <ChevronUpIcon class="size-4 shrink-0 text-muted-foreground" />
    </DropdownMenu.Trigger>
    <!-- As wide as the bar, less a small margin each side. -->
    <DropdownMenu.Content
      side="top"
      align="center"
      sideOffset={6}
      class="w-[calc(var(--bits-dropdown-menu-anchor-width)-1rem)]"
    >
      {#each workspaces.list as workspace (workspace.id)}
        <DropdownMenu.Item
          class="h-10 {inWorkspace && workspace.id === target?.id ? 'font-semibold' : ''}"
          onSelect={() => navigate(`/workspaces/${workspace.slug}`)}
        >
          <WorkspaceIcon name={workspace.icon} size={16} />
          <span class="truncate">{workspace.name}</span>
        </DropdownMenu.Item>
      {/each}
      {#if workspaces.list.length > 0}
        <DropdownMenu.Separator />
      {/if}
      <!-- The overview and a new workspace, side by side on one line, a thin rule between them. -->
      <div class="flex items-stretch">
        <DropdownMenu.Item class="h-10 flex-1 justify-center {home ? 'font-semibold' : ''}" onSelect={() => navigate("/")}>
          All
        </DropdownMenu.Item>
        <span class="my-2 w-px shrink-0 bg-border" aria-hidden="true"></span>
        <DropdownMenu.Item class="h-10 flex-1 justify-center" onSelect={() => (creating = true)}>
          <PlusIcon /> New
        </DropdownMenu.Item>
      </div>
    </DropdownMenu.Content>
  </DropdownMenu.Root>
</div>

<NewWorkspaceDialog bind:open={creating} />
