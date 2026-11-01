<script lang="ts">
  import { untrack } from "svelte";
  import { toast } from "svelte-sonner";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";

  // Asks before anything that deletes or removes. With `requireText`, the button waits until it's
  // typed exactly. onConfirm throws with the words to show when it fails, and the dialog stays open.
  let {
    open = $bindable(false),
    title,
    message,
    confirmLabel,
    requireText,
    onConfirm,
  }: {
    open?: boolean;
    title: string;
    message: string;
    confirmLabel: string;
    requireText?: string;
    onConfirm: () => Promise<void>;
  } = $props();

  let typed = $state("");
  let busy = $state(false);

  $effect(() => {
    if (open) untrack(() => (typed = ""));
  });

  async function confirm() {
    busy = true;
    try {
      await onConfirm();
      open = false;
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      busy = false;
    }
  }
</script>

<AlertDialog.Root bind:open>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{title}</AlertDialog.Title>
      <AlertDialog.Description>{message}</AlertDialog.Description>
    </AlertDialog.Header>
    {#if requireText !== undefined}
      <div class="space-y-2">
        <Label for="confirm-text">Type “{requireText}” to confirm</Label>
        <Input id="confirm-text" autocomplete="off" bind:value={typed} />
      </div>
    {/if}
    <AlertDialog.Footer>
      <AlertDialog.Cancel>Cancel</AlertDialog.Cancel>
      <Button onclick={confirm} disabled={busy || (requireText !== undefined && typed !== requireText)}>{confirmLabel}</Button>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
