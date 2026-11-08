<script lang="ts">
  import LogOutIcon from "@lucide/svelte/icons/log-out";
  import MoonIcon from "@lucide/svelte/icons/moon";
  import SunIcon from "@lucide/svelte/icons/sun";
  import UserIcon from "@lucide/svelte/icons/user";
  import { mode, toggleMode } from "mode-watcher";
  import { admin } from "$lib/admin.svelte";
  import SignOutDialog from "$lib/components/SignOutDialog.svelte";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { SYSTEM_PAGES } from "$lib/nav";
  import { followLink, router } from "$lib/router.svelte";
  import { session } from "$lib/session.svelte";

  // Phones only: what the bottom of the sidebar holds (you, the theme, sign out), plus System for admins.
  let { open = $bindable(false) }: { open?: boolean } = $props();

  let confirmSignOut = $state(false);

  const isAdmin = $derived(session.user?.role === "admin");
  const route = $derived(router.route);
  const modeLabel = $derived(mode.current === "dark" ? "Switch to light mode" : "Switch to dark mode");

  function go(event: MouseEvent) {
    followLink(event);
    open = false;
  }

  function signOut() {
    open = false;
    confirmSignOut = true;
  }

  // The current page is marked with weight, never colour.
  function rowClass(active: boolean): string {
    return `flex h-11 w-full items-center gap-3 rounded-md px-3 text-left outline-none hover:bg-muted
      focus-visible:ring-2 focus-visible:ring-ring ${active ? "font-semibold" : ""}`;
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content
    class="top-auto bottom-0 left-0 max-h-[calc(100svh-1rem)] max-w-full translate-x-0 translate-y-0 gap-3 overflow-y-auto rounded-b-none pb-[calc(1rem+env(safe-area-inset-bottom))] sm:max-w-full
           data-open:slide-in-from-bottom data-closed:slide-out-to-bottom data-open:zoom-in-100 data-closed:zoom-out-100"
  >
    <Dialog.Title class="sr-only">You</Dialog.Title>
    <div class="space-y-0.5 px-3 pt-1 pr-10">
      <p class="truncate font-medium">{session.user?.name}</p>
      <p class="truncate font-mono text-xs text-muted-foreground">{session.user?.email}</p>
    </div>

    <div class="space-y-0.5">
      <a href="/account" onclick={go} class={rowClass(route.name === "account")}
         aria-current={route.name === "account" ? "page" : undefined}>
        <UserIcon class="size-4" /> Account settings
      </a>
      <button type="button" class={rowClass(false)} onclick={toggleMode}>
        {#if mode.current === "dark"}<SunIcon class="size-4" />{:else}<MoonIcon class="size-4" />{/if}
        {modeLabel}
      </button>
    </div>

    {#if isAdmin}
      <section class="space-y-0.5 border-t pt-3" aria-labelledby="you-system">
        <h2 id="you-system" class="px-3 pb-1 text-[11px] font-medium tracking-wider text-muted-foreground uppercase">System</h2>
        {#each SYSTEM_PAGES as page (page.name)}
          <a href={page.href} onclick={go} class={rowClass(route.name === page.name)}
             aria-current={route.name === page.name ? "page" : undefined}>
            <span class="flex-1">{page.label}</span>
            {#if page.name === "admin-accounts" && admin.pendingSignups > 0}
              <span class="flex items-center gap-1.5 text-xs font-medium">
                <span class="size-2 rounded-full bg-status-warn" aria-hidden="true"></span>
                {admin.pendingSignups} waiting
              </span>
            {/if}
          </a>
        {/each}
      </section>
    {/if}

    <div class="border-t pt-3">
      <button type="button" class={rowClass(false)} onclick={signOut}>
        <LogOutIcon class="size-4" /> Sign out
      </button>
    </div>
  </Dialog.Content>
</Dialog.Root>

<SignOutDialog bind:open={confirmSignOut} />
