/** Times arrive from the API as UTC ISO strings; people see them in their own time. */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** "just now", "5 min ago", "2 h ago", then a local date. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const ago = now.getTime() - then.getTime();
  if (ago < MINUTE) return "just now";
  if (ago < HOUR) return `${Math.floor(ago / MINUTE)} min ago`;
  if (ago < DAY) return `${Math.floor(ago / HOUR)} h ago`;
  return then.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: then.getFullYear() === now.getFullYear() ? undefined : "numeric",
  });
}

export function localDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** "4 s ago" for things read every few seconds, then as relativeTime. */
export function secondsAgo(iso: string, now: Date = new Date()): string {
  const ago = now.getTime() - new Date(iso).getTime();
  return ago < MINUTE ? `${Math.max(0, Math.floor(ago / 1000))} s ago` : relativeTime(iso, now);
}

/** Local "HH:MM". */
export function clockTime(iso: string): string {
  const at = new Date(iso);
  return `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
}

/** How long since: "40 s", "2 min", "6 h", "3 days". */
export function elapsed(iso: string, now: Date = new Date()): string {
  const ago = Math.max(0, now.getTime() - new Date(iso).getTime());
  if (ago < MINUTE) return `${Math.floor(ago / 1000)} s`;
  if (ago < HOUR) return `${Math.floor(ago / MINUTE)} min`;
  if (ago < DAY) return `${Math.floor(ago / HOUR)} h`;
  const days = Math.floor(ago / DAY);
  return `${days} ${days === 1 ? "day" : "days"}`;
}
