<script lang="ts">
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { signOut } from "$lib/session.svelte";

  // Asks before signing out; the sidebar and the phone's You panel both open it.
  let { open = $bindable(false) }: { open?: boolean } = $props();
</script>

<ConfirmDialog
  bind:open
  title="Sign out?"
  message="You'll need your email and password to sign in again."
  confirmLabel="Sign out"
  onConfirm={signOut}
/>
