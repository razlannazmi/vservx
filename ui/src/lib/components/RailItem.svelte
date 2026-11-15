<script lang="ts" module>
  /**
   * - How far a tooltip or menu opens from a rail item, so it clears the rail.
   * - A rail item's right edge sits 10px inside the rail's outer edge; 8px more leaves a gap.
   */
  export const RAIL_POPUP_OFFSET = 18;

  /**
   * - A square icon slot for the collapsed sidebar.
   * - Icons carry no text to give weight, so the current page is marked with a fill.
   */
  export function railClass(active: boolean): string {
    return `relative grid size-9 shrink-0 place-items-center rounded-md outline-none focus-visible:ring-2
      focus-visible:ring-sidebar-ring ${active ? "bg-sidebar-accent text-sidebar-foreground" : "text-sidebar-foreground/75 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground"}`;
  }
</script>

<script lang="ts">
  import type { Snippet } from "svelte";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { followLink } from "$lib/router.svelte";

  type Props = {
    label: string;
    href?: string;
    active?: boolean;
    onclick?: () => void;
    onpointerenter?: () => void;
    onpointerleave?: () => void;
    onfocus?: () => void;
    onblur?: () => void;
    "aria-expanded"?: boolean;
    children: Snippet;
  };

  let { label, href, active = false, onclick, children, ...rest }: Props = $props();
</script>

<!-- A link with href, else a button. The label names it aloud and in a tooltip to its right. -->
<Tooltip.Root>
  <Tooltip.Trigger {...rest} class={railClass(active)} aria-label={label}
                   aria-current={href && active ? "page" : undefined} onclick={href ? followLink : onclick}>
    {#snippet child({ props })}
      {#if href}
        <a {...props} {href}>{@render children()}</a>
      {:else}
        <button {...props} type="button">{@render children()}</button>
      {/if}
    {/snippet}
  </Tooltip.Trigger>
  <Tooltip.Content side="right" sideOffset={RAIL_POPUP_OFFSET}>{label}</Tooltip.Content>
</Tooltip.Root>
