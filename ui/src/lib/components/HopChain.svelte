<script lang="ts">
  import {
    CONTAINERS,
    chainScene,
    containerStep,
    HOPS,
    hopStep,
    linkStep,
    STILL_SCENE,
    untilNextChange,
    type ChainScene,
  } from "$lib/hops";
  import { prefersReducedMotion } from "$lib/motion";
  import { TONE_DOT } from "$lib/servers";
  import { INSTANCE_TONE, INSTANCE_WORDS } from "$lib/watch";

  // The dark half of the sign-in page: vservx reaching a GPU server through its jump hosts, then finding its vLLMs.
  // Always dark, whatever the theme. Decoration only, so screen readers skip it.
  let scene = $state<ChainScene>(chainScene(0));

  const lit = (step: number) => (scene.lit > step ? "" : undefined);
  const last = HOPS.length - 1;
  // Every name gets the longest name's width, so the notes after them line up in one column.
  const nameWidth = `${Math.max(...HOPS.map((hop) => hop.name.length))}ch`;

  $effect(() => {
    if (prefersReducedMotion()) {
      scene = STILL_SCENE;
      return;
    }
    let start = performance.now();
    let pausedAt: number | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const step = () => {
      const t = performance.now() - start;
      scene = chainScene(t);
      timer = setTimeout(step, untilNextChange(t));
    };
    // A hidden tab stops the loop; it carries on from the same moment when the tab is back.
    const onVisibility = () => {
      if (document.hidden) {
        if (pausedAt !== null) return;
        clearTimeout(timer);
        pausedAt = performance.now();
      } else if (pausedAt !== null) {
        start += performance.now() - pausedAt;
        pausedAt = null;
        step();
      }
    };
    step();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  });
</script>

<div
  class="dark relative flex h-36 shrink-0 flex-col border-b bg-background text-foreground lg:h-auto lg:w-1/2 lg:border-r lg:border-b-0"
  aria-hidden="true"
>
  <div
    class={[
      "flex flex-1 items-center px-6 pb-6 transition-opacity duration-250 lg:px-16 lg:pb-0",
      !scene.shown && "opacity-0",
    ]}
  >
    <!-- Across the strip on narrow screens, down the half on wide ones. -->
    <div class="flex w-full items-start font-code lg:w-auto lg:flex-col" style:--name-width={nameWidth}>
      {#each HOPS as hop, i (hop.name)}
        <div
          class="group relative flex flex-col items-center gap-2 text-[11px] text-foreground/35 transition-colors duration-250 data-lit:text-foreground lg:flex-row lg:gap-3 lg:text-sm"
          data-lit={lit(hopStep(i))}
        >
          <span
            class="size-2.5 shrink-0 rounded-full border-[1.5px] border-foreground/25 bg-background transition-colors duration-250 group-data-lit:border-foreground group-data-lit:bg-foreground"
          ></span>
          <span class="lg:min-w-(--name-width)">{hop.name}</span>
          {#if hop.note}
            <span
              class="hidden text-xs text-muted-foreground opacity-0 transition-opacity duration-250 group-data-lit:opacity-100 lg:inline"
            >
              {hop.note}
            </span>
          {/if}
          {#if i === last}
            <ul class="absolute top-1/2 left-full ml-14 hidden -translate-y-1/2 flex-col gap-3 lg:flex">
              {#each CONTAINERS as container, j (container.port)}
                <li
                  class="flex translate-y-1 items-center gap-2.5 rounded-md border px-3.5 py-2 text-xs whitespace-nowrap opacity-0 transition duration-250 ease-out data-lit:translate-y-0 data-lit:opacity-100"
                  data-lit={lit(containerStep(j))}
                >
                  <span class="text-foreground">vllm :{container.port}</span>
                  <span class="size-1.5 rounded-full {TONE_DOT[INSTANCE_TONE[container.state]]}"></span>
                  <span class="text-muted-foreground">{INSTANCE_WORDS[container.state]}</span>
                </li>
              {/each}
            </ul>
          {/if}
        </div>
        {#if i < last}
          <!-- The link draws from one hop towards the next: left to right, or top to bottom. -->
          <div
            class="group relative mx-2 mt-[4.5px] h-px min-w-4 flex-1 bg-foreground/15 lg:mx-0 lg:mt-0 lg:ml-[4.5px] lg:h-16 lg:w-px lg:min-w-0 lg:flex-none"
            data-lit={lit(linkStep(i))}
          >
            <span
              class="absolute inset-0 origin-left scale-x-0 bg-foreground transition-transform duration-250 ease-in-out group-data-lit:scale-100 lg:origin-top lg:scale-x-100 lg:scale-y-0"
            ></span>
          </div>
        {/if}
      {/each}
    </div>
  </div>

  <p class="absolute bottom-3 left-6 text-xs lg:bottom-6 lg:left-16">
    <span class="font-code text-muted-foreground">vservx</span>
    <span class="hidden text-foreground/45 lg:inline">&ensp;Point it at a server, see your vLLMs.</span>
  </p>
</div>
