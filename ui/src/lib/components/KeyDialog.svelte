<script lang="ts">
  import { untrack } from "svelte";
  import { toast } from "svelte-sonner";
  import { api, errorMessage, type SavedKeyRead } from "$lib/api/client";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";

  // With `replacing`, the dialog swaps that key's private key; otherwise it adds a new key.
  let {
    open = $bindable(false),
    workspaceId,
    replacing = null,
    onSaved,
  }: {
    open?: boolean;
    workspaceId: number;
    replacing?: SavedKeyRead | null;
    onSaved: (key: SavedKeyRead) => void | Promise<void>;
  } = $props();

  let name = $state("");
  let privateKey = $state("");
  let passphrase = $state("");
  let busy = $state(false);

  // Cleared on every open and close, so a private key doesn't linger in the page.
  $effect(() => {
    void open;
    untrack(() => {
      name = "";
      privateKey = "";
      passphrase = "";
    });
  });

  async function readFile(event: Event) {
    const file = (event.currentTarget as HTMLInputElement).files?.[0];
    if (file) privateKey = await file.text();
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    const path = { workspace_id: workspaceId };
    // A passphrase is only needed for an encrypted key.
    const secret = { private_key: privateKey, passphrase: passphrase || null };
    const { data, error } = replacing
      ? await api.PATCH("/api/workspaces/{workspace_id}/ssh-keys/{key_id}", {
          params: { path: { ...path, key_id: replacing.id } },
          body: secret,
        })
      : await api.POST("/api/workspaces/{workspace_id}/ssh-keys", { params: { path }, body: { name: name.trim(), ...secret } });
    busy = false;
    if (error || !data) {
      toast.error(errorMessage(error, "Couldn't save the key"));
      return;
    }
    open = false;
    await onSaved(data);
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-md">
    <form class="space-y-4" onsubmit={submit}>
      <Dialog.Header>
        <Dialog.Title>{replacing ? `Replace “${replacing.name}”` : "Add a key"}</Dialog.Title>
        <Dialog.Description>
          {replacing
            ? "Servers that use this key sign in with the new one from now on."
            : "A private key this workspace's servers can sign in with. vservx never shows it again."}
        </Dialog.Description>
      </Dialog.Header>
      {#if !replacing}
        <div class="space-y-2">
          <Label for="key-name">Name</Label>
          <Input id="key-name" required maxlength={255} placeholder="work-deploy" bind:value={name} />
        </div>
      {/if}
      <div class="space-y-2">
        <Label for="key-file">Private key</Label>
        <Input id="key-file" type="file" onchange={readFile} />
        <textarea
          aria-label="Private key text"
          required
          spellcheck="false"
          autocomplete="off"
          rows="6"
          placeholder="…or paste it here: -----BEGIN OPENSSH PRIVATE KEY-----"
          class="w-full min-w-0 resize-y rounded-lg border border-input bg-transparent px-2.5 py-2 font-mono text-xs outline-none
                 placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
          bind:value={privateKey}
        ></textarea>
      </div>
      <div class="space-y-2">
        <Label for="key-passphrase">Passphrase <span class="font-normal text-muted-foreground">(only for an encrypted key)</span></Label>
        <Input id="key-passphrase" type="password" autocomplete="off" bind:value={passphrase} />
      </div>
      <Dialog.Footer>
        <Button type="button" variant="outline" onclick={() => (open = false)}>Cancel</Button>
        <Button type="submit" disabled={busy}>{replacing ? "Replace key" : "Add key"}</Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
