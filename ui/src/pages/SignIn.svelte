<script lang="ts">
  import AuthLayout from "$lib/components/AuthLayout.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { followLink } from "$lib/router.svelte";
  import { session, signIn } from "$lib/session.svelte";

  // Shown above the form, e.g. while a database upgrade waits.
  let { note }: { note?: string } = $props();

  let email = $state("");
  let password = $state("");
  let message = $state<string | null>(null);
  let busy = $state(false);

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    message = null;
    const result = await signIn(email, password);
    busy = false;
    if (!result.ok) message = result.message;
  }
</script>

<AuthLayout>
  <form class="w-full max-w-sm space-y-6" onsubmit={submit}>
    <div class="space-y-1.5">
      <h1 class="text-2xl font-semibold tracking-tight">Sign in</h1>
      {#if note}
        <p class="text-sm text-muted-foreground">{note}</p>
      {/if}
    </div>

    <div class="space-y-4">
      <div class="space-y-2">
        <Label for="email">Email</Label>
        <Input id="email" type="email" autocomplete="username" required bind:value={email} />
      </div>
      <div class="space-y-2">
        <Label for="password">Password</Label>
        <Input id="password" type="password" autocomplete="current-password" required bind:value={password} />
      </div>
    </div>

    {#if message}
      <p role="alert" class="rounded-lg border px-3 py-2 text-sm">{message}</p>
    {/if}

    <Button type="submit" class="w-full" disabled={busy}>Sign in</Button>

    {#if session.signupOpen}
      <p class="text-center text-sm text-muted-foreground">
        New here?
        <a href="/sign-up" onclick={followLink} class="text-foreground underline underline-offset-4">Create an account</a>
      </p>
    {/if}
  </form>
</AuthLayout>
