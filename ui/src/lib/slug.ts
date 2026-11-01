/** A workspace's address is its name, not its id: /workspaces/home-lab. */

const LONGEST = 60;

/** "Home Lab (EU)" → "home-lab-eu": accents dropped, anything else between words a dash. */
export function slugify(name: string): string {
  const slug = name
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, LONGEST)
    .replace(/-$/, "");
  return slug || "workspace";
}

/** Names are unique ignoring case, but "Home Lab" and "home-lab" still make one address, so a
 * repeat gets a number. Older workspaces claim first, so a new one never moves an existing link. */
export function withSlugs<T extends { id: number; name: string }>(list: T[]): (T & { slug: string })[] {
  const taken = new Set<string>();
  const slugs = new Map<number, string>();
  for (const each of [...list].sort((a, b) => a.id - b.id)) {
    const base = slugify(each.name);
    let slug = base;
    for (let n = 2; taken.has(slug); n++) slug = `${base}-${n}`;
    taken.add(slug);
    slugs.set(each.id, slug);
  }
  return list.map((each) => ({ ...each, slug: slugs.get(each.id)! }));
}
