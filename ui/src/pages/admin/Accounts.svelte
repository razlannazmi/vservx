<script lang="ts">
  import EllipsisIcon from "@lucide/svelte/icons/ellipsis";
  import { onMount, untrack } from "svelte";
  import { toast } from "svelte-sonner";
  import { admin } from "$lib/admin.svelte";
  import { api, errorMessage, type AccountRead, type AccountUpdate } from "$lib/api/client";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { localDateTime, relativeTime } from "$lib/format";
  import { loadSession, session } from "$lib/session.svelte";

  let accounts = $state<AccountRead[]>([]);
  let signupOpen = $state(false);
  let rejecting = $state<AccountRead | null>(null);
  let confirmReject = $state(false);
  let settingPassword = $state<AccountRead | null>(null);
  let passwordOpen = $state(false);
  let newPassword = $state("");
  let savingPassword = $state(false);

  const pending = $derived(accounts.filter((account) => account.approved_at === null));
  const approved = $derived(accounts.filter((account) => account.approved_at !== null));
  const me = $derived(session.user?.id ?? null);

  onMount(() => {
    void load();
    void loadSettings();
  });

  // The typed password goes when the dialog opens or closes.
  $effect(() => {
    void passwordOpen;
    untrack(() => (newPassword = ""));
  });

  async function load() {
    const { data } = await api.GET("/api/admin/accounts");
    accounts = data ?? [];
    // Keeps the sidebar's "waiting" count in step.
    admin.pendingSignups = accounts.filter((account) => account.approved_at === null).length;
  }

  async function loadSettings() {
    const { data } = await api.GET("/api/admin/settings");
    if (data) signupOpen = data.signup_open;
  }

  async function setSignupOpen(open: boolean) {
    signupOpen = open;
    const { data, error } = await api.PATCH("/api/admin/settings", { body: { signup_open: open } });
    if (error || !data) {
      toast.error(errorMessage(error, "Couldn't change sign-up"));
      await loadSettings();
      return;
    }
    signupOpen = data.signup_open;
    session.signupOpen = data.signup_open;
  }

  async function approve(account: AccountRead) {
    const { error } = await api.POST("/api/admin/accounts/{account_id}/approve", {
      params: { path: { account_id: account.id } },
    });
    if (error) toast.error(errorMessage(error, "Couldn't approve the account"));
    await load();
  }

  function askToReject(account: AccountRead) {
    rejecting = account;
    confirmReject = true;
  }

  async function reject() {
    if (!rejecting) return;
    const { error } = await api.DELETE("/api/admin/accounts/{account_id}", { params: { path: { account_id: rejecting.id } } });
    if (error) throw new Error(errorMessage(error, "Couldn't reject the sign-up"));
    await load();
  }

  async function update(account: AccountRead, body: AccountUpdate, fallback: string): Promise<boolean> {
    const { error } = await api.PATCH("/api/admin/accounts/{account_id}", {
      params: { path: { account_id: account.id } },
      body,
    });
    // Includes "vservx needs at least one active admin".
    if (error) toast.error(errorMessage(error, fallback));
    // Changing your own role or status changes what you may see.
    if (!error && account.id === me) await loadSession();
    await load();
    return !error;
  }

  function askForPassword(account: AccountRead) {
    settingPassword = account;
    passwordOpen = true;
  }

  async function savePassword(event: SubmitEvent) {
    event.preventDefault();
    if (!settingPassword) return;
    savingPassword = true;
    const saved = await update(settingPassword, { password: newPassword }, "Couldn't set the password");
    savingPassword = false;
    if (saved) {
      passwordOpen = false;
      toast.success(`New password set for ${settingPassword.name}`);
    }
  }
</script>

{#snippet actions(account: AccountRead)}
  <DropdownMenu.Root>
    <DropdownMenu.Trigger class={buttonVariants({ variant: "ghost", size: "icon-sm" })} aria-label={`Actions for ${account.name}`}>
      <EllipsisIcon />
    </DropdownMenu.Trigger>
    <DropdownMenu.Content align="end">
      <DropdownMenu.Item
        onSelect={() =>
          update(account, { role: account.role === "admin" ? "member" : "admin" }, "Couldn't change the role")}
      >
        {account.role === "admin" ? "Remove admin" : "Make admin"}
      </DropdownMenu.Item>
      <DropdownMenu.Item
        onSelect={() => update(account, { is_active: !account.is_active }, "Couldn't change the account")}
      >
        {account.is_active ? "Disable" : "Enable"}
      </DropdownMenu.Item>
      {#if account.id !== me}
        <!-- Your own password changes on the Account page, which checks the current one. -->
        <DropdownMenu.Separator />
        <DropdownMenu.Item onSelect={() => askForPassword(account)}>Set new password…</DropdownMenu.Item>
      {/if}
    </DropdownMenu.Content>
  </DropdownMenu.Root>
{/snippet}

<div class="flex-1 overflow-y-auto p-4 md:p-6">
  <div class="mx-auto max-w-5xl space-y-6">
    <header class="flex flex-wrap items-end justify-between gap-4">
      <div class="space-y-1.5">
        <h1 class="text-xl font-semibold tracking-tight">Accounts</h1>
        <p class="text-sm text-muted-foreground">Everyone who can sign in to vservx.</p>
      </div>
      <div class="flex items-center gap-4 rounded-lg border bg-card px-4 py-2.5">
        <Label for="signup-open" class="flex-col items-start gap-1">
          Sign-up open
          <span class="text-xs font-normal text-muted-foreground">
            {signupOpen ? "Anyone can ask for an account." : "The sign-in page has no sign-up link."}
          </span>
        </Label>
        <Switch id="signup-open" bind:checked={() => signupOpen, setSignupOpen} />
      </div>
    </header>

    {#if pending.length > 0}
      <section class="space-y-4" aria-labelledby="accounts-waiting">
        <h2 id="accounts-waiting" class="flex items-center gap-2 font-medium">
          <span class="size-2 rounded-full bg-status-warn" aria-hidden="true"></span> Waiting for approval
        </h2>
        <ul class="divide-y rounded-xl border bg-card">
          {#each pending as account (account.id)}
            <li class="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
              <div class="min-w-0 flex-1">
                <p class="truncate font-medium">{account.name}</p>
                <p class="truncate font-mono text-xs text-muted-foreground">{account.email}</p>
              </div>
              <span class="text-xs text-muted-foreground" title={localDateTime(account.created_at)}>
                signed up {relativeTime(account.created_at)}
              </span>
              <Button size="sm" onclick={() => approve(account)}>Approve</Button>
              <Button size="sm" variant="outline" onclick={() => askToReject(account)}>Reject</Button>
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    <section class="space-y-4" aria-labelledby="accounts-all">
      <h2 id="accounts-all" class="font-medium">All accounts</h2>
      <!-- Phones: one row per account, its details stacked, the same actions menu. -->
      <ul class="divide-y rounded-xl border bg-card md:hidden">
        {#each approved as account (account.id)}
          <li class="px-4 py-3 text-sm">
            <div class="flex items-center justify-between gap-3">
              <p class="min-w-0 truncate font-medium">
                {account.name}{#if account.id === me}{" "}<span class="font-normal text-muted-foreground">(you)</span>{/if}
              </p>
              {@render actions(account)}
            </div>
            <p class="font-mono text-xs break-all text-muted-foreground">{account.email}</p>
            <p class="mt-0.5 text-xs text-muted-foreground">
              {account.role === "admin" ? "Admin" : "Member"} · {account.is_active ? "Active" : "Disabled"} ·
              <span title={account.last_login_at ? localDateTime(account.last_login_at) : undefined}>
                last sign-in {account.last_login_at ? relativeTime(account.last_login_at) : "never"}
              </span>
            </p>
          </li>
        {/each}
      </ul>
      <div class="hidden rounded-xl border bg-card md:block">
        <Table.Root>
          <Table.Header>
            <Table.Row>
              <Table.Head class="pl-4">Name</Table.Head>
              <Table.Head>Email</Table.Head>
              <Table.Head>Role</Table.Head>
              <Table.Head>Status</Table.Head>
              <Table.Head>Last sign-in</Table.Head>
              <Table.Head class="pr-4"><span class="sr-only">Actions</span></Table.Head>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {#each approved as account (account.id)}
              <Table.Row>
                <Table.Cell class="pl-4 font-medium">
                  {account.name}{#if account.id === me}{" "}<span class="font-normal text-muted-foreground">(you)</span>{/if}
                </Table.Cell>
                <Table.Cell class="font-mono text-xs">{account.email}</Table.Cell>
                <Table.Cell>{account.role === "admin" ? "Admin" : "Member"}</Table.Cell>
                <Table.Cell class={account.is_active ? "" : "text-muted-foreground"}>{account.is_active ? "Active" : "Disabled"}</Table.Cell>
                <Table.Cell title={account.last_login_at ? localDateTime(account.last_login_at) : undefined}>
                  {account.last_login_at ? relativeTime(account.last_login_at) : "never"}
                </Table.Cell>
                <Table.Cell class="pr-4 text-right">{@render actions(account)}</Table.Cell>
              </Table.Row>
            {/each}
          </Table.Body>
        </Table.Root>
      </div>
    </section>
  </div>
</div>

<ConfirmDialog
  bind:open={confirmReject}
  title={`Reject ${rejecting?.name ?? ""}?`}
  message="Their sign-up is deleted. They can sign up again while sign-up is open."
  confirmLabel="Reject"
  onConfirm={reject}
/>

<Dialog.Root bind:open={passwordOpen}>
  <Dialog.Content class="sm:max-w-sm">
    <form class="space-y-4" onsubmit={savePassword}>
      <Dialog.Header>
        <Dialog.Title>New password for {settingPassword?.name}</Dialog.Title>
        <Dialog.Description>They're signed out everywhere, and sign in again with this one.</Dialog.Description>
      </Dialog.Header>
      <div class="space-y-2">
        <Label for="admin-new-password">New password</Label>
        <Input id="admin-new-password" type="password" autocomplete="new-password" required minlength={8} maxlength={128} bind:value={newPassword} />
      </div>
      <Dialog.Footer>
        <Button type="button" variant="outline" onclick={() => (passwordOpen = false)}>Cancel</Button>
        <Button type="submit" disabled={savingPassword}>Set password</Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
