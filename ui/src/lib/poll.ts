/** Asking the backend again and again, only while someone can see the page. */

/**
 * Runs `fn` now, then every `ms` while the tab is visible, and again as soon as a hidden tab comes
 * back. A run never starts while the last one is still going. Returns a function that stops it.
 */
export function every(ms: number, fn: () => unknown): () => void {
  let stopped = false;
  let running = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  function schedule() {
    clearTimeout(timer);
    if (!stopped && document.visibilityState === "visible") timer = setTimeout(run, ms);
  }

  async function run() {
    if (stopped || running) return;
    clearTimeout(timer);
    running = true;
    try {
      await fn();
    } finally {
      running = false;
      schedule();
    }
  }

  function onVisibilityChange() {
    if (document.visibilityState === "visible") void run();
    else clearTimeout(timer);
  }

  document.addEventListener("visibilitychange", onVisibilityChange);
  void run();
  return () => {
    stopped = true;
    clearTimeout(timer);
    document.removeEventListener("visibilitychange", onVisibilityChange);
  };
}
