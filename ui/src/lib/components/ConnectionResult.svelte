<script lang="ts">
  import type { ConnectionTestResult, LastTestRead } from "$lib/api/client";
  import { relativeTime } from "$lib/format";
  import { failureTone, failureWords, TONE_DOT } from "$lib/servers";

  // A test just run (hop by hop), or the one the server remembers (its summary only).
  let { result }: { result: ConnectionTestResult | LastTestRead } = $props();

  const hops = $derived("hops" in result ? result.hops : null);
  const summary = $derived.by(() => {
    if ("hops" in result) {
      // On failure the failing hop is the last one attempted.
      const failed = result.ok ? null : (result.hops.at(-1) ?? null);
      return { at: null, failure: failed?.reason ?? null, hop: failed?.name ?? null, message: failed?.message ?? null };
    }
    return { at: result.at, failure: result.failure, hop: result.failed_hop, message: result.message };
  });
  const tone = $derived(result.ok ? "ok" : failureTone(summary.failure));
  const headline = $derived(result.ok ? "Connected" : capitalise(failureWords(summary.failure)));
  const facts = $derived(
    [
      !result.ok && summary.hop ? `at ${summary.hop}` : null,
      `in ${(result.elapsed_ms / 1000).toFixed(1)} s`,
      summary.at ? relativeTime(summary.at) : null,
      result.ok && result.hostname ? `hostname “${result.hostname}”` : null,
    ].filter((fact) => fact !== null),
  );

  function capitalise(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1);
  }
</script>

<div class="space-y-2 rounded-lg border px-3 py-2.5 text-sm">
  <p class="flex flex-wrap items-center gap-x-2 gap-y-1">
    <span class="size-2 shrink-0 rounded-full {TONE_DOT[tone]}" aria-hidden="true"></span>
    <span class="font-medium">{headline}</span>
    <span class="text-muted-foreground">{facts.join(" · ")}</span>
  </p>
  {#if !result.ok && summary.message && !hops}
    <p class="text-muted-foreground">{summary.message}</p>
  {/if}
  {#if hops && hops.length > 0}
    <ol class="space-y-1.5 border-t pt-2">
      {#each hops as hop, index (index)}
        <li class="flex gap-2">
          <span class="mt-1.5 size-2 shrink-0 rounded-full {TONE_DOT[hop.ok ? 'ok' : failureTone(hop.reason)]}" aria-hidden="true"></span>
          <div class="min-w-0">
            <p><span class="font-medium">{hop.name}</span> · {hop.ok ? "OK" : failureWords(hop.reason)}</p>
            {#if !hop.ok && hop.message}
              <p class="text-muted-foreground">{hop.message}</p>
            {/if}
            {#if hop.fingerprint}
              <p class="font-mono text-xs break-all text-muted-foreground">{hop.fingerprint}</p>
            {/if}
          </div>
        </li>
      {/each}
    </ol>
  {/if}
</div>
