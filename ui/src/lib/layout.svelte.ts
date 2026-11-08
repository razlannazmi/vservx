/** Phone or not: the one place the layout breakpoint lives in script. It matches Tailwind's `md`
 * (48rem), so `max-md:` classes and `phone.current` always agree. Use it only where behaviour differs;
 * where only looks differ, use the classes. */

import { MediaQuery } from "svelte/reactivity";

export const phone = new MediaQuery("width < 48rem");
