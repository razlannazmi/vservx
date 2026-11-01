/** Who is signed in, and whether the database lets anyone in at all. */

import { api, onApiSignal, type UserRead } from "$lib/api/client";
import { navigate, router } from "$lib/router.svelte";

export type DatabaseView = "current" | "upgrade_required" | "newer_than_app";

export const session = $state<{
  user: UserRead | null;
  loaded: boolean;
  database: DatabaseView;
  signupOpen: boolean;
}>({ user: null, loaded: false, database: "current", signupOpen: false });

const PUBLIC_ROUTES = new Set(["sign-in", "sign-up"]);

// Where someone was going when they had to sign in first.
let returnTo: string | null = null;

function databaseView(state: string): DatabaseView {
  return state === "upgrade_required" || state === "newer_than_app" ? state : "current";
}

/** Send someone signed out to the sign-in page (remembering where they were), and someone
 * signed in away from it. */
export function guardRoute(): void {
  if (!session.loaded) return;
  const isPublic = PUBLIC_ROUTES.has(router.route.name);
  if (!session.user && !isPublic) {
    returnTo = router.path;
    navigate("/sign-in", { replace: true });
  } else if (session.user && isPublic) {
    navigate("/", { replace: true });
  }
}

export async function loadSession(): Promise<void> {
  const { data: health } = await api.GET("/api/health");
  if (health) {
    session.database = databaseView(health.database);
    session.signupOpen = health.signup_open;
  }
  const { data: me } = await api.GET("/api/auth/me");
  session.user = me ?? null;
  session.loaded = true;
  guardRoute();
}

export async function signIn(email: string, password: string): Promise<{ ok: true } | { ok: false; message: string }> {
  const { error, response } = await api.POST("/api/auth/login", { body: { email, password } });
  if (error) {
    if (response.status === 401) return { ok: false, message: "Incorrect email or password" };
    // A non-admin while an upgrade waits: only an admin can do anything now.
    if (response.status === 503) return { ok: false, message: "An admin needs to upgrade the database." };
    // Waiting for approval, or disabled: the backend says which.
    const detail = (error as { detail?: unknown }).detail;
    return { ok: false, message: typeof detail === "string" ? detail : "Couldn't sign in" };
  }
  const { data: me } = await api.GET("/api/auth/me");
  session.user = me ?? null;
  const destination = returnTo && !returnTo.startsWith("/sign-") ? returnTo : "/";
  returnTo = null;
  navigate(destination, { replace: true });
  return { ok: true };
}

export async function signOut(): Promise<void> {
  await api.POST("/api/auth/logout");
  // A full reload, so nothing of this account stays in memory for the next one.
  location.replace("/sign-in");
}

onApiSignal((signal) => {
  if (signal === "signed-out") {
    session.user = null;
    guardRoute();
  } else {
    session.database = signal === "database_upgrade_required" ? "upgrade_required" : "newer_than_app";
  }
});
