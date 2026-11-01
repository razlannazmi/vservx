<script lang="ts">
  import { api, type AccountSummary } from "$lib/api/client";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";

  // Find an approved account by name or email and choose it. `exclude` hides accounts by id.
  let {
    chosen = $bindable(null),
    exclude = [],
    id,
  }: { chosen?: AccountSummary | null; exclude?: number[]; id: string } = $props();

  let query = $state("");
  let results = $state<AccountSummary[]>([]);
  let searched = $state(false);

  // Asks the server once typing has paused for 250 ms.
  $effect(() => {
    const text = query.trim();
    results = [];
    searched = false;
    if (!text) return;
    const timer = setTimeout(() => void search(text), 250);
    return () => clearTimeout(timer);
  });

  async function search(text: string) {
    const { data } = await api.GET("/api/accounts", { params: { query: { q: text } } });
    // Typed on meanwhile: a newer search is coming.
    if (text !== query.trim()) return;
    results = (data ?? []).filter((account) => !exclude.includes(account.id));
    searched = true;
  }
</script>

{#if chosen}
  <div class="flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-sm">
    <div class="min-w-0">
      <p class="truncate font-medium">{chosen.name}</p>
      <p class="truncate font-mono text-xs text-muted-foreground">{chosen.email}</p>
    </div>
    <Button size="sm" variant="ghost" onclick={() => (chosen = null)}>Change</Button>
  </div>
{:else}
  <Input {id} type="search" autocomplete="off" placeholder="Name or email" bind:value={query} />
  {#if results.length > 0}
    <ul class="max-h-56 overflow-y-auto rounded-lg border" aria-label="Matching accounts">
      {#each results as account (account.id)}
        <li>
          <button
            type="button"
            class="flex w-full flex-col items-start px-3 py-2 text-left text-sm outline-none hover:bg-muted focus-visible:bg-muted"
            onclick={() => (chosen = account)}
          >
            <span class="font-medium">{account.name}</span>
            <span class="font-mono text-xs text-muted-foreground">{account.email}</span>
          </button>
        </li>
      {/each}
    </ul>
  {:else if searched}
    <p class="text-sm text-muted-foreground">No approved account matches.</p>
  {/if}
{/if}
