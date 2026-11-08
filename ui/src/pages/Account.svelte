<script lang="ts">
  import { onMount } from "svelte";
  import { toast } from "svelte-sonner";
  import { api, errorMessage } from "$lib/api/client";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { session, signOutEverywhere } from "$lib/session.svelte";

  let name = $state("");
  let confirmSignOutEverywhere = $state(false);
  let renaming = $state(false);
  let currentPassword = $state("");
  let newPassword = $state("");
  let changingPassword = $state(false);

  onMount(() => {
    name = session.user?.name ?? "";
  });

  async function rename(event: SubmitEvent) {
    event.preventDefault();
    renaming = true;
    const { data, error } = await api.PATCH("/api/auth/me", { body: { name: name.trim() } });
    renaming = false;
    if (error || !data) {
      toast.error(errorMessage(error, "Couldn't change your name"));
      return;
    }
    session.user = data;
    toast.success("Name changed");
  }

  async function changePassword(event: SubmitEvent) {
    event.preventDefault();
    changingPassword = true;
    const { error } = await api.POST("/api/auth/me/password", {
      body: { current_password: currentPassword, new_password: newPassword },
    });
    changingPassword = false;
    if (error) {
      toast.error(errorMessage(error, "Couldn't change your password"));
      return;
    }
    // The response brought a new session cookie, so this session carries on.
    currentPassword = "";
    newPassword = "";
    toast.success("Password changed. Your other sessions are signed out.");
  }
</script>

<div class="flex-1 overflow-y-auto p-4 md:p-6">
  <div class="mx-auto max-w-2xl space-y-6">
    <header class="space-y-1.5">
      <h1 class="text-xl font-semibold tracking-tight">Your account</h1>
      <p class="text-sm text-muted-foreground">
        <span class="font-mono break-all">{session.user?.email}</span> · {session.user?.role === "admin" ? "Admin" : "Member"}
      </p>
    </header>

    <section class="space-y-4 rounded-xl border bg-card p-5" aria-labelledby="account-name">
      <h2 id="account-name" class="font-medium">Name</h2>
      <form class="flex gap-2" onsubmit={rename}>
        <Input aria-label="Your name" required maxlength={255} bind:value={name} />
        <Button type="submit" variant="outline" disabled={renaming || name.trim() === session.user?.name}>Save</Button>
      </form>
    </section>

    <section class="space-y-4 rounded-xl border bg-card p-5" aria-labelledby="account-password">
      <div class="space-y-1.5">
        <h2 id="account-password" class="font-medium">Password</h2>
        <p class="text-sm text-muted-foreground">Changing it signs you out everywhere else.</p>
      </div>
      <form class="space-y-4" onsubmit={changePassword}>
        <div class="space-y-2">
          <Label for="account-current-password">Current password</Label>
          <Input id="account-current-password" type="password" autocomplete="current-password" required bind:value={currentPassword} />
        </div>
        <div class="space-y-2">
          <Label for="account-new-password">New password</Label>
          <Input
            id="account-new-password"
            type="password"
            autocomplete="new-password"
            required
            minlength={8}
            maxlength={128}
            bind:value={newPassword}
          />
          <p class="text-xs text-muted-foreground">At least 8 characters.</p>
        </div>
        <Button type="submit" disabled={changingPassword}>Change password</Button>
      </form>
    </section>

    <section class="space-y-4 rounded-xl border bg-card p-5" aria-labelledby="account-sessions">
      <div class="space-y-1.5">
        <h2 id="account-sessions" class="font-medium">Sessions</h2>
        <p class="text-sm text-muted-foreground">
          Signs out every browser and stops every API token of yours, this one included. Use it if a
          device was lost or a token was shared.
        </p>
      </div>
      <Button variant="outline" onclick={() => (confirmSignOutEverywhere = true)}>Sign out everywhere</Button>
    </section>
  </div>
</div>

<ConfirmDialog
  bind:open={confirmSignOutEverywhere}
  title="Sign out everywhere?"
  message="Every browser and API token of yours is signed out, including this one. You'll need your email and password to sign in again."
  confirmLabel="Sign out everywhere"
  onConfirm={signOutEverywhere}
/>
