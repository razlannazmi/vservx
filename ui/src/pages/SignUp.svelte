<script lang="ts">
  import { api, errorMessage } from "$lib/api/client";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { followLink } from "$lib/router.svelte";

  let name = $state("");
  let email = $state("");
  let password = $state("");
  let message = $state<string | null>(null);
  let sent = $state(false);
  let busy = $state(false);

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    message = null;
    const { error, response } = await api.POST("/api/auth/signup", { body: { name, email, password } });
    busy = false;
    if (!error) {
      sent = true;
    } else if (response.status === 409) {
      message = "That email is already registered";
    } else {
      message = errorMessage(error, "Couldn't create the account");
    }
  }
</script>

<div class="flex min-h-svh items-center justify-center p-6">
  <div class="w-full max-w-sm space-y-6">
    <div class="space-y-1.5">
      <p class="font-mono text-sm text-muted-foreground">vservx</p>
      <h1 class="text-2xl font-semibold tracking-tight">Create an account</h1>
    </div>

    {#if sent}
      <p role="status" class="rounded-lg border px-3 py-2 text-sm">
        An admin needs to approve your account before you can sign in.
      </p>
      <a href="/sign-in" onclick={followLink} class="inline-block text-sm underline underline-offset-4">Back to sign in</a>
    {:else}
      <form class="space-y-6" onsubmit={submit}>
        <div class="space-y-4">
          <div class="space-y-2">
            <Label for="name">Name</Label>
            <Input id="name" autocomplete="name" required maxlength={255} bind:value={name} />
          </div>
          <div class="space-y-2">
            <Label for="email">Email</Label>
            <Input id="email" type="email" autocomplete="email" required bind:value={email} />
          </div>
          <div class="space-y-2">
            <Label for="password">Password</Label>
            <Input id="password" type="password" autocomplete="new-password" required minlength={8} maxlength={128}
                   bind:value={password} />
            <p class="text-xs text-muted-foreground">At least 8 characters.</p>
          </div>
        </div>

        {#if message}
          <p role="alert" class="rounded-lg border px-3 py-2 text-sm">{message}</p>
        {/if}

        <Button type="submit" class="w-full" disabled={busy}>Create account</Button>
        <p class="text-center text-sm text-muted-foreground">
          Have an account?
          <a href="/sign-in" onclick={followLink} class="text-foreground underline underline-offset-4">Sign in</a>
        </p>
      </form>
    {/if}
  </div>
</div>
