<script lang="ts">
  import { prefersReducedMotion } from "$lib/motion";
  import { iconComponent } from "$lib/workspace-icons";

  let {
    name,
    size = 24,
    animate = false,
    class: className = "",
  }: { name: string | null | undefined; size?: number; animate?: boolean; class?: string } = $props();

  const Icon = $derived(iconComponent(name));
  // movingicons ignores reduced motion, so it's decided here. The icon never takes the pointer:
  // its own hover would animate regardless, so whatever holds it says when it moves.
  const moving = $derived(animate && !prefersReducedMotion());
</script>

<!-- Decoration only: a name or label always sits beside it, and the package's own role="img"
     would read the icon's file name aloud. -->
<span aria-hidden="true" class={`pointer-events-none inline-flex shrink-0 ${className}`}>
  <Icon {size} animate={moving} />
</span>
