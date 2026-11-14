<script lang="ts">
  import InfoIcon from "@lucide/svelte/icons/info";
  import { untrack } from "svelte";
  import { toast } from "svelte-sonner";
  import { slide } from "svelte/transition";
  import {
    api,
    errorMessage,
    type ConnectionTestResult,
    type SavedKeyRead,
    type ServerCreate,
    type ServerKind,
    type ServerRead,
    type ServerUpdate,
    type ThisMachineRead,
  } from "$lib/api/client";
  import ConnectionResult from "$lib/components/ConnectionResult.svelte";
  import KeyDialog from "$lib/components/KeyDialog.svelte";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { duration, easeOut } from "$lib/motion";
  import { session } from "$lib/session.svelte";

  // With `server`, the dialog edits it; otherwise it adds a new one.
  let {
    open = $bindable(false),
    workspaceId,
    server = null,
    servers,
    keys,
    onSaved,
    onDeleted,
    onKeyAdded,
  }: {
    open?: boolean;
    workspaceId: number;
    server?: ServerRead | null;
    servers: ServerRead[];
    keys: SavedKeyRead[];
    onSaved: (server: ServerRead) => void | Promise<void>;
    onDeleted: () => void | Promise<void>;
    onKeyAdded: (key: SavedKeyRead) => void | Promise<void>;
  } = $props();

  const PASSWORD = "password";
  const NEW_KEY = "new-key";
  const DIRECT = "direct";
  const KIND_WORDS: Record<ServerKind, string> = { ssh: "Over SSH", this_machine: "This machine" };

  let kind = $state<ServerKind>("ssh");
  // Whether this machine can be watched without SSH; asked for only when an app admin has the dialog open.
  let thisMachine = $state<ThisMachineRead | null>(null);
  let form = $state<HTMLFormElement | null>(null);
  // When the sudo password is needed, behind the info button as on a snapshot's command.
  let sudoInfoOpen = $state(false);
  let name = $state("");
  let host = $state("");
  let port = $state<number | null>(22);
  let username = $state("");
  // "password", or a saved key's id.
  let signsIn = $state(PASSWORD);
  let password = $state("");
  // Used only to run docker ps / docker inspect through sudo.
  let sudoPassword = $state("");
  let removeSudoPassword = $state(false);
  let jump = $state(DIRECT);
  let jumpOnly = $state(false);
  let result = $state<ConnectionTestResult | null>(null);
  let saving = $state(false);
  let testing = $state(false);
  let addingKey = $state(false);
  let confirmingDelete = $state(false);
  let deleting = $state(false);
  let deleteRefusal = $state<string | null>(null);

  const isAdmin = $derived(session.user?.role === "admin");
  const local = $derived(kind === "this_machine");
  // Anyone but an app admin who edits this machine can only rename it.
  const renameOnly = $derived(!isAdmin && server?.kind === "this_machine");
  const usesKey = $derived(signsIn !== PASSWORD);
  // Stored secrets never reach the browser: an empty field keeps the saved password.
  const keepsPassword = $derived(!usesKey && server?.auth_type === "password" && server.has_password);
  const keepsSudoPassword = $derived(server?.has_sudo_password ?? false);
  const signsInLabel = $derived(
    usesKey ? `Saved key “${keys.find((each) => String(each.id) === signsIn)?.name ?? "…"}”` : "Password",
  );
  const jumpChoices = $derived(servers.filter((each) => each.id !== server?.id && each.kind !== "this_machine"));
  const jumpLabel = $derived(
    jump === DIRECT ? "None, connect directly" : (servers.find((each) => String(each.id) === jump)?.name ?? "…"),
  );

  // Each opening starts from the server being edited, or blank.
  $effect(() => {
    if (open) untrack(reset);
  });

  async function loadThisMachine() {
    thisMachine = null;
    const { data } = await api.GET("/api/admin/this-machine");
    thisMachine = data ?? null;
    // Picked before the answer came: name it now, unless a name was typed meanwhile.
    nameAfterThisMachine();
  }

  // Picking this machine names a blank server after it.
  function nameAfterThisMachine() {
    if (local && !name.trim() && thisMachine) name = thisMachine.hostname;
  }

  function chooseKind(value: string) {
    kind = value as ServerKind;
    nameAfterThisMachine();
  }

  function reset() {
    kind = server?.kind ?? "ssh";
    if (isAdmin) void loadThisMachine();
    name = server?.name ?? "";
    host = server?.host ?? "";
    port = server?.port ?? 22;
    username = server?.username ?? "";
    signsIn = server?.auth_type === "key" && server.ssh_key_id !== null ? String(server.ssh_key_id) : PASSWORD;
    password = "";
    sudoPassword = "";
    removeSudoPassword = false;
    jump = server?.jump_server_id != null ? String(server.jump_server_id) : DIRECT;
    jumpOnly = server?.jump_only ?? false;
    result = null;
  }

  // "Add a new key…" opens the key dialog and keeps the current choice until a key is saved.
  function chooseSignIn(value: string) {
    if (value === NEW_KEY) addingKey = true;
    else signsIn = value;
  }

  async function keyAdded(key: SavedKeyRead) {
    await onKeyAdded(key);
    signsIn = String(key.id);
  }

  function settings(): ServerCreate {
    // This machine has no host, port, user, sign-in or jump host: send only kind and name. The API fills the
    // schema defaults (port, jump_only), so the cast only skips them in the type.
    if (local) return { name: name.trim(), kind } as ServerCreate;
    return {
      kind,
      name: name.trim(),
      host: host.trim(),
      port: port ?? 22,
      username: username.trim(),
      auth_type: usesKey ? "key" : "password",
      ssh_key_id: usesKey ? Number(signsIn) : null,
      password: usesKey ? null : password,
      jump_server_id: jump === DIRECT ? null : Number(jump),
      jump_only: jumpOnly,
    };
  }

  function changes(): ServerUpdate {
    if (renameOnly) return { name: name.trim() };
    const { password: typed, ...rest } = settings();
    // An empty sudo password field keeps the saved one; the tick removes it.
    const sudo: ServerUpdate = removeSudoPassword
      ? { sudo_password: null }
      : sudoPassword
        ? { sudo_password: sudoPassword }
        : {};
    // Switching to a key clears the stored password; an empty password field keeps it.
    if (local) return { name: rest.name, kind, ...sudo };
    if (usesKey) return { ...rest, ...sudo, password: null };
    return typed ? { ...rest, ...sudo, password: typed } : { ...rest, ...sudo };
  }

  async function test() {
    if (!form?.reportValidity()) return;
    if (!local && !usesKey && !password) {
      // The saved password never comes back to the browser, so it can't be tried from here.
      toast.error("Type the password to test these settings");
      return;
    }
    testing = true;
    result = null;
    const { data, error } = await api.POST("/api/workspaces/{workspace_id}/servers/test", {
      params: { path: { workspace_id: workspaceId } },
      body: local && sudoPassword ? { ...settings(), sudo_password: sudoPassword } : settings(),
    });
    testing = false;
    if (error || !data) {
      toast.error(errorMessage(error, "Couldn't run the test"));
      return;
    }
    result = data;
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    saving = true;
    const path = { workspace_id: workspaceId };
    const { data, error } = server
      ? await api.PATCH("/api/workspaces/{workspace_id}/servers/{server_id}", {
          params: { path: { ...path, server_id: server.id } },
          body: changes(),
        })
      : await api.POST("/api/workspaces/{workspace_id}/servers", {
          params: { path },
          body: { ...settings(), sudo_password: sudoPassword || null },
        });
    saving = false;
    if (error || !data) {
      toast.error(errorMessage(error, "Couldn't save the server"));
      return;
    }
    open = false;
    await onSaved(data);
  }

  function askToDelete() {
    deleteRefusal = null;
    confirmingDelete = true;
  }

  async function remove() {
    if (!server) return;
    deleting = true;
    const { error } = await api.DELETE("/api/workspaces/{workspace_id}/servers/{server_id}", {
      params: { path: { workspace_id: workspaceId, server_id: server.id } },
    });
    deleting = false;
    if (error) {
      // Refused while other servers jump through this one: the backend says how many.
      deleteRefusal = errorMessage(error, "Couldn't delete the server");
      return;
    }
    confirmingDelete = false;
    open = false;
    await onDeleted();
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="max-h-[90svh] overflow-y-auto sm:max-w-lg">
    <form bind:this={form} class="space-y-4" onsubmit={save}>
      <Dialog.Header>
        <Dialog.Title>{server ? `Edit ${server.name}` : "Add a server"}</Dialog.Title>
        <Dialog.Description>{local ? "Watched from the machine vservx runs on, without SSH." : "How vservx reaches it over SSH."}</Dialog.Description>
      </Dialog.Header>

      {#if isAdmin}
        <div class="space-y-2">
          <Label for="server-kind">Reached</Label>
          <Select.Root type="single" bind:value={() => kind, chooseKind}>
            <Select.Trigger id="server-kind" class="w-full">{KIND_WORDS[kind]}</Select.Trigger>
            <Select.Content>
              <Select.Item value="ssh" label={KIND_WORDS.ssh} />
              <Select.Item value="this_machine" label={KIND_WORDS.this_machine} disabled={thisMachine?.available === false} />
            </Select.Content>
          </Select.Root>
          {#if thisMachine?.available === false}
            <p class="text-xs text-muted-foreground">This machine: {thisMachine.reason}</p>
          {/if}
        </div>
      {/if}

      <div class="grid grid-cols-[minmax(0,1fr)_6rem] gap-3">
        <div class="col-span-2 space-y-2">
          <Label for="server-name">Name</Label>
          <Input id="server-name" required maxlength={255} placeholder="gpu-7" bind:value={name} />
        </div>
        {#if !local && !renameOnly}
          <div class="space-y-2">
            <Label for="server-host">Host</Label>
            <Input id="server-host" class="font-mono" required maxlength={255} placeholder="10.0.4.17" bind:value={host} />
          </div>
          <div class="space-y-2">
            <Label for="server-port">Port</Label>
            <Input id="server-port" class="font-mono" type="number" required min={1} max={65535} bind:value={port} />
          </div>
          <div class="col-span-2 space-y-2">
            <Label for="server-user">User</Label>
            <Input id="server-user" class="font-mono" required maxlength={255} placeholder="ubuntu" bind:value={username} />
          </div>
        {/if}
      </div>

      {#if !local && !renameOnly}
        <div class="space-y-2">
          <Label for="server-signs-in">Signs in with</Label>
          <Select.Root type="single" bind:value={() => signsIn, chooseSignIn}>
            <Select.Trigger id="server-signs-in" class="w-full">{signsInLabel}</Select.Trigger>
            <Select.Content>
              <Select.Item value={PASSWORD} label="Password" />
              {#each keys as key (key.id)}
                <Select.Item value={String(key.id)} label={`Saved key “${key.name}”`} />
              {/each}
              <Select.Separator />
              <Select.Item value={NEW_KEY} label="Add a new key…" />
            </Select.Content>
          </Select.Root>
        </div>

        {#if !usesKey}
          <div class="space-y-2">
            <Label for="server-password">Password</Label>
            <Input
              id="server-password"
              type="password"
              autocomplete="new-password"
              required={!keepsPassword}
              placeholder={keepsPassword ? "Unchanged" : undefined}
              bind:value={password}
            />
            {#if keepsPassword}
              <p class="text-xs text-muted-foreground">Leave it empty to keep the saved password.</p>
            {/if}
          </div>
        {/if}
      {/if}

      {#if !renameOnly}
        <div class="space-y-2">
          <!-- Held to the label's height, so the info button doesn't push the input down. -->
          <div class="flex h-3.5 items-center gap-1.5">
            <Label for="server-sudo-password">Sudo password</Label>
            <Button
              size="icon-xs"
              variant="outline"
              class="dark:bg-background"
              aria-label="When the sudo password is needed"
              title="When the sudo password is needed"
              aria-expanded={sudoInfoOpen}
              aria-controls="server-sudo-info"
              onclick={() => (sudoInfoOpen = !sudoInfoOpen)}
            >
              <InfoIcon aria-hidden="true" />
            </Button>
          </div>
          {#if sudoInfoOpen}
            <p
              id="server-sudo-info"
              class="rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
              transition:slide={{ duration: duration(150), easing: easeOut }}
            >
              Only if Docker needs it.
            </p>
          {/if}
          <Input
            id="server-sudo-password"
            type="password"
            autocomplete="new-password"
            placeholder={keepsSudoPassword && !removeSudoPassword ? "Unchanged" : undefined}
            disabled={removeSudoPassword}
            bind:value={sudoPassword}
          />
          {#if keepsSudoPassword}
            <p class="text-xs text-muted-foreground">Leave it empty to keep the saved sudo password.</p>
          {:else if !usesKey && !local}
            <p class="text-xs text-muted-foreground">Leave empty to use the sign-in password.</p>
          {/if}
        </div>

        {#if keepsSudoPassword}
          <div class="flex items-center justify-between gap-4">
            <Label for="server-remove-sudo">Remove the saved sudo password</Label>
            <Switch id="server-remove-sudo" bind:checked={removeSudoPassword} />
          </div>
        {/if}
      {/if}

      {#if !local && !renameOnly}
        <div class="space-y-2">
          <Label for="server-jump">Jump host</Label>
          <Select.Root type="single" bind:value={jump}>
            <Select.Trigger id="server-jump" class="w-full">{jumpLabel}</Select.Trigger>
            <Select.Content>
              <Select.Item value={DIRECT} label="None, connect directly" />
              {#each jumpChoices as each (each.id)}
                <Select.Item value={String(each.id)} label={each.name} />
              {/each}
            </Select.Content>
          </Select.Root>
        </div>

        <div class="flex items-center justify-between gap-4">
          <Label for="server-jump-only" class="flex-col items-start gap-1">
            Use only as a jump host
            <span class="text-xs font-normal text-muted-foreground">Listed under Jump hosts, for reaching other servers.</span>
          </Label>
          <Switch id="server-jump-only" bind:checked={jumpOnly} />
        </div>
      {/if}

      {#if result}
        <ConnectionResult {result} />
      {/if}

      <Dialog.Footer class="sm:justify-between">
        <div>
          {#if server}
            <Button type="button" variant="ghost" onclick={askToDelete}>Delete</Button>
          {/if}
        </div>
        <div class="flex flex-col-reverse gap-2 sm:flex-row">
          {#if !renameOnly}
            <Button type="button" variant="outline" onclick={test} disabled={testing}>{testing ? "Testing…" : "Test"}</Button>
          {/if}
          <Button type="button" variant="outline" onclick={() => (open = false)}>Cancel</Button>
          <Button type="submit" disabled={saving}>Save</Button>
        </div>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>

<KeyDialog bind:open={addingKey} {workspaceId} onSaved={keyAdded} />

{#if server}
  <AlertDialog.Root bind:open={confirmingDelete}>
    <AlertDialog.Content>
      <AlertDialog.Header>
        <AlertDialog.Title>Delete {server.name}?</AlertDialog.Title>
        <AlertDialog.Description>
          vservx forgets this server and its stored password. Nothing on the server itself changes.
        </AlertDialog.Description>
      </AlertDialog.Header>
      {#if deleteRefusal}
        <p role="alert" class="rounded-lg border px-3 py-2 text-sm">{deleteRefusal}</p>
      {/if}
      <AlertDialog.Footer>
        <AlertDialog.Cancel>Cancel</AlertDialog.Cancel>
        <Button onclick={remove} disabled={deleting}>Delete</Button>
      </AlertDialog.Footer>
    </AlertDialog.Content>
  </AlertDialog.Root>
{/if}
