import { expect, test } from "vitest";
import { classifyResponse, type ServerRead } from "./api/client";
import { serverStatus } from "./servers";
import { slugify, withSlugs } from "./slug";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

test("401 signs out except on sign-in", async () => {
  expect(await classifyResponse(json(401, { detail: "Not authenticated" }), "http://x/api/workspaces")).toBe("signed-out");
  expect(
    await classifyResponse(json(401, { detail: "Incorrect email or password" }), "http://x/api/auth/login"),
  ).toBeNull();
});

test("503 upgrade codes", async () => {
  const url = "http://x/api/workspaces";
  expect(await classifyResponse(json(503, { code: "database_upgrade_required" }), url)).toBe("database_upgrade_required");
  expect(await classifyResponse(json(503, { code: "database_newer_than_app" }), url)).toBe("database_newer_than_app");
  expect(await classifyResponse(json(503, { detail: "other" }), url)).toBeNull();
});

test("server status follows the latest test", () => {
  const at = new Date("2026-10-31T12:00:00Z");
  // The rest of a server doesn't matter here.
  const base = { id: 1, name: "gpu-1", host: "10.0.0.1", port: 22, username: "ubuntu" };
  const s = (last_test: unknown) => ({ ...base, last_test }) as unknown as ServerRead;
  expect(serverStatus(s(null), at)).toEqual({ tone: "none", label: "never tested" });
  expect(serverStatus(s({ ok: true, at: "2026-10-31T11:55:00Z" }), at)).toEqual({ tone: "ok", label: "OK · tested 5 min ago" });
  expect(serverStatus(s({ ok: false, failure: "host_key_changed", at: "2026-10-31T11:00:00Z" }), at).tone).toBe("warn");
  expect(serverStatus(s({ ok: false, failure: "unreachable", at: "2026-10-31T11:40:00Z" }), at)).toEqual({
    tone: "bad",
    label: "unreachable · 20 min ago",
  });
});

test("a workspace name becomes an address", () => {
  expect(slugify("Homelab")).toBe("homelab");
  expect(slugify("  Home Lab (EU) ")).toBe("home-lab-eu");
  expect(slugify("Café Ünïcode")).toBe("cafe-unicode");
  expect(slugify("服务器")).toBe("workspace");
});

test("repeated names get a number, oldest first", () => {
  const list = [
    { id: 7, name: "homelab" },
    { id: 3, name: "Homelab" },
    { id: 5, name: "homelab 2" },
  ];
  expect(withSlugs(list).map((each) => each.slug)).toEqual(["homelab-3", "homelab", "homelab-2"]);
});
