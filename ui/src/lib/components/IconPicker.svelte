<script lang="ts">
  import WorkspaceIcon from "$lib/components/WorkspaceIcon.svelte";
  import { iconName, WORKSPACE_ICONS } from "$lib/workspace-icons";

  let { value = $bindable(), label = "Icon" }: { value: string; label?: string } = $props();

  // The icon under the pointer or keyboard focus plays its animation.
  let active = $state<string | null>(null);
  const buttons: HTMLButtonElement[] = [];
  const current = $derived(iconName(value));

  const STEPS: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };

  // A radio group: the arrow keys move the choice, and Tab leaves the group.
  function onkeydown(event: KeyboardEvent, index: number) {
    const step = STEPS[event.key];
    if (!step) return;
    event.preventDefault();
    const next = (index + step + WORKSPACE_ICONS.length) % WORKSPACE_ICONS.length;
    value = WORKSPACE_ICONS[next].name;
    buttons[next]?.focus();
  }
</script>

<div role="radiogroup" aria-label={label} class="grid grid-cols-8 gap-1">
  {#each WORKSPACE_ICONS as icon, index (icon.name)}
    {@const checked = icon.name === current}
    <button
      bind:this={buttons[index]}
      type="button"
      role="radio"
      aria-checked={checked}
      aria-label={icon.label}
      title={icon.label}
      tabindex={checked ? 0 : -1}
      class={`grid aspect-square place-items-center rounded-md border outline-none focus-visible:ring-2 focus-visible:ring-ring
        ${checked ? "border-foreground/40 bg-accent text-foreground" : "border-transparent text-muted-foreground hover:bg-accent hover:text-foreground"}`}
      onclick={() => (value = icon.name)}
      onkeydown={(event) => onkeydown(event, index)}
      onpointerenter={() => (active = icon.name)}
      onpointerleave={() => (active = null)}
      onfocus={() => (active = icon.name)}
      onblur={() => (active = null)}
    >
      <WorkspaceIcon name={icon.name} size={20} animate={active === icon.name} />
    </button>
  {/each}
</div>
