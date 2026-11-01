import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";

/** Something every screen needs to react to, whatever request it came from. */
export type ApiSignal = "signed-out" | "database_upgrade_required" | "database_newer_than_app";

type Schemas = components["schemas"];
export type UserRead = Schemas["UserRead"];
export type WorkspaceRead = Schemas["WorkspaceRead"];
export type WorkspaceRole = Schemas["WorkspaceRole"];
export type ServerRead = Schemas["ServerRead"];
export type ServerCreate = Schemas["ServerCreate"];
export type ServerUpdate = Schemas["ServerUpdate"];
export type SavedKeyRead = Schemas["SavedKeyRead"];
export type LastTestRead = Schemas["LastTestRead"];
export type ConnectionTestResult = Schemas["ConnectionTestResult"];
export type HopResult = Schemas["HopResult"];
export type MemberRead = Schemas["MemberRead"];
export type AccountSummary = Schemas["AccountSummary"];
export type AccountRead = Schemas["AccountRead"];
export type AccountUpdate = Schemas["AccountUpdate"];
export type AdminWorkspaceRead = Schemas["AdminWorkspaceRead"];
export type DatabaseRead = Schemas["DatabaseRead"];

const listeners = new Set<(signal: ApiSignal) => void>();

export function onApiSignal(listener: (signal: ApiSignal) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// On these a 401 answers the form ("wrong password"); it doesn't mean the session ended.
const FORM_401_PATHS = new Set(["/api/auth/login", "/api/auth/me/password"]);
const DATABASE_CODES = new Set<string>(["database_upgrade_required", "database_newer_than_app"]);

/** What a response means for the app as a whole, beyond the request that got it. */
export async function classifyResponse(response: Response, url: string = response.url): Promise<ApiSignal | null> {
  if (response.status === 401) {
    return FORM_401_PATHS.has(new URL(url, "http://localhost").pathname) ? null : "signed-out";
  }
  if (response.status === 503) {
    try {
      // A clone, so the caller can still read the body.
      const body: unknown = await response.clone().json();
      const code = (body as { code?: unknown } | null)?.code;
      if (typeof code === "string" && DATABASE_CODES.has(code)) return code as ApiSignal;
    } catch {
      // Not JSON: some other 503.
    }
  }
  return null;
}

const signals: Middleware = {
  onRequest({ request }) {
    // The backend refuses cookie-authenticated writes without it (cross-site request forgery).
    request.headers.set("X-Vservx", "1");
    return request;
  },
  async onResponse({ request, response }) {
    const signal = await classifyResponse(response, request.url);
    if (signal) for (const listener of listeners) listener(signal);
    return response;
  },
};

/** The typed API client. Same origin: the session cookie goes along by itself. */
export const api = createClient<paths>({ baseUrl: "" });
api.use(signals);

/** The words to show for a failed request: FastAPI's detail, or the first validation message. */
export function errorMessage(error: unknown, fallback = "Something went wrong"): string {
  const detail = (error as { detail?: unknown } | null | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg;
  return fallback;
}
