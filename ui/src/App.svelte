<script lang="ts">
  import { ModeWatcher } from "mode-watcher";
  import { onMount } from "svelte";
  import { fly } from "svelte/transition";
  import AppShell from "$lib/components/AppShell.svelte";
  import { Toaster } from "$lib/components/ui/sonner/index.js";
  import { phone } from "$lib/layout.svelte";
  import { navigate, router } from "$lib/router.svelte";
  import { duration, easeOut } from "$lib/motion";
  import { guardRoute, loadSession, session } from "$lib/session.svelte";
  import { loadWorkspaces, workspaceBySlug, workspaces } from "$lib/workspaces.svelte";
  import DatabaseNotice from "./pages/DatabaseNotice.svelte";
  import { isOwner } from "$lib/permissions";
  import Account from "./pages/Account.svelte";
  import AdminAccounts from "./pages/admin/Accounts.svelte";
  import AdminDatabase from "./pages/admin/Database.svelte";
  import AdminWorkspaces from "./pages/admin/Workspaces.svelte";
  import Keys from "./pages/Keys.svelte";
  import Members from "./pages/Members.svelte";
  import Servers from "./pages/Servers.svelte";
  import WorkspaceSettings from "./pages/WorkspaceSettings.svelte";
  import SignIn from "./pages/SignIn.svelte";
  import SignUp from "./pages/SignUp.svelte";
  import Welcome from "./pages/Welcome.svelte";
  import WorkspacesPage from "./pages/Workspaces.svelte";

  onMount(() => {
    void loadSession();
  });

  // Back and forward can land on any page, signed in or not.
  $effect(() => {
    void router.route;
    guardRoute();
  });

  // Each account loads its own workspaces.
  $effect(() => {
    if (session.user && session.database === "current") void loadWorkspaces();
  });

  const route = $derived(router.route);
  const isAdmin = $derived(session.user?.role === "admin");
  const workspace = $derived("workspaceSlug" in route ? workspaceBySlug(route.workspaceSlug) : null);
  // A fresh page, sliding in, for each page and each workspace, so nothing of one shows while the
  // next loads. Moving between servers stays on the same page; the details have their own motion.
  const pageKey = $derived(`${route.name}:${workspace?.id ?? ""}`);

  // The phone tabs keep leading into this workspace after you leave it for your account or an admin page.
  $effect(() => {
    if (workspace) workspaces.lastId = workspace.id;
  });

  // A workspace that isn't in the list (gone, renamed, or never yours): check once more, then go home.
  $effect(() => {
    if ("workspaceSlug" in route && workspaces.loaded && workspace === null) void checkWorkspace(route.workspaceSlug);
  });

  async function checkWorkspace(slug: string) {
    await loadWorkspaces();
    if (workspaceBySlug(slug) === null && "workspaceSlug" in router.route && router.route.workspaceSlug === slug) {
      navigate("/", { replace: true });
    }
  }
</script>

<ModeWatcher />
<!-- On phones toasts drop from the top, clear of the tabs. -->
<Toaster position={phone.current ? "top-center" : "bottom-right"} />

{#if !session.loaded}
  <!-- Nothing until we know who this is, so no page flashes by. -->
{:else if session.database !== "current"}
  <DatabaseNotice />
{:else if !session.user}
  {#if route.name === "sign-up"}
    <SignUp />
  {:else}
    <SignIn />
  {/if}
{:else}
  <AppShell>
    {#key pageKey}
      <div class="flex min-h-0 flex-1 flex-col" in:fly={{ y: 6, duration: duration(200), easing: easeOut }}>
        {#if route.name === "home"}
          <!-- Home is every workspace as a card; with none yet, a way to make one. -->
          {#if workspaces.loaded && workspaces.list.length === 0}
            <Welcome />
          {:else if workspaces.loaded}
            <WorkspacesPage />
          {/if}
        {:else if "workspaceSlug" in route}
          {#if workspace}
            {#if route.name === "servers"}
              <Servers {workspace} serverId={route.serverId} instance={route.instance} />
            {:else if route.name === "keys"}
              <Keys {workspace} />
            {:else if route.name === "members"}
              <Members {workspace} />
            {:else if route.name === "settings" && isOwner(workspace.role)}
              <WorkspaceSettings {workspace} />
            {:else if route.name === "settings"}
              <div class="p-4 md:p-6">
                <h1 class="text-xl font-semibold">Settings</h1>
                <p class="text-sm text-muted-foreground">Only the workspace's owner can change its settings.</p>
              </div>
            {/if}
          {/if}
        {:else if route.name === "account"}
          <Account />
        {:else if isAdmin && route.name === "admin-accounts"}
          <AdminAccounts />
        {:else if isAdmin && route.name === "admin-workspaces"}
          <AdminWorkspaces />
        {:else if isAdmin && route.name === "admin-database"}
          <AdminDatabase />
        {:else}
          <div class="p-4 md:p-6">
            <h1 class="text-xl font-semibold">Page not found</h1>
            <p class="text-sm text-muted-foreground">There's nothing at this address.</p>
          </div>
        {/if}
      </div>
    {/key}
  </AppShell>
{/if}
