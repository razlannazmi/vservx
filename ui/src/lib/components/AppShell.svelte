<script lang="ts">
  import type { Snippet } from "svelte";
  import { loadPendingSignups } from "$lib/admin.svelte";
  import Sidebar from "$lib/components/Sidebar.svelte";
  import TabBar from "$lib/components/TabBar.svelte";
  import TopBar from "$lib/components/TopBar.svelte";
  import UpgradedAlert from "$lib/components/UpgradedAlert.svelte";
  import WorkspaceBar from "$lib/components/WorkspaceBar.svelte";
  import { session } from "$lib/session.svelte";

  let { children }: { children: Snippet } = $props();

  const isAdmin = $derived(session.user?.role === "admin");

  // Both layouts show how many accounts wait for approval: the sidebar's System list, the phone's You tab.
  $effect(() => {
    if (isAdmin) void loadPendingSignups();
  });
</script>

<!-- From md (768px) up, the sidebar beside the page. Narrower, a top bar, the page, the workspace bar, then tabs.
     The padding keeps clear of a notch or home bar (viewport-fit=cover); it is 0 on screens without one.
     On phones the tab bar pads the bottom itself. -->
<div
  class="flex h-svh flex-col pt-[env(safe-area-inset-top)] pr-[env(safe-area-inset-right)] pl-[env(safe-area-inset-left)]
         md:flex-row md:pb-[env(safe-area-inset-bottom)]"
>
  <Sidebar />
  <div class="contents md:hidden"><TopBar /></div>
  <main class="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
    <div class="px-4 pt-4 empty:hidden md:px-6"><UpgradedAlert /></div>
    {@render children()}
  </main>
  <div class="contents md:hidden"><WorkspaceBar /><TabBar /></div>
</div>
