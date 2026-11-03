import { expect, test } from "vitest";
import { classifyResponse, type ServerRead, type WatchedInstanceRead, type WatchSummaryRead } from "./api/client";
import { clockTime } from "./format";
import { serverStatus } from "./servers";
import { slugify, withSlugs } from "./slug";
import { cardStatus, gpuLabel, instanceReason } from "./watch";

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

const now = new Date("2026-11-01T12:00:00Z");
const server = { id: 1, name: "gpu-7", jump_only: false, last_test: null } as unknown as ServerRead;
const sum = (state: string, counts = {}, docker = "plain", since: string | null = null) =>
  ({ server_id: 1, state, since, docker, counts }) as unknown as WatchSummaryRead;

test("card status follows watching", () => {
  expect(cardStatus(server, sum("not_tested"))).toEqual({ tone: "none", label: "not tested yet" });
  expect(cardStatus(server, sum("connected"))).toEqual({ tone: "ok", label: "no instances" });
  expect(cardStatus(server, sum("connected", { ready: 3, crashed: 1, starting: 1 }))).toEqual({
    tone: "bad",
    label: "5 instances · 1 crashed · 1 starting",
  });
  expect(cardStatus(server, sum("connected", { ready: 1, restarting: 1 })).tone).toBe("warn");
  expect(cardStatus(server, sum("connected", { ready: 1 }, "needs_sudo_password"))).toEqual({
    tone: "warn",
    label: "needs sudo password",
  });
  const since = "2026-11-01T11:02:00Z";
  expect(cardStatus(server, sum("unreachable", {}, "unknown", since)).label).toBe(`unreachable · since ${clockTime(since)}`);
  expect(cardStatus(server, undefined)).toEqual(serverStatus(server));
});

test("a stopped instance says why", () => {
  const crashed = {
    state: "crashed",
    exit_code: 137,
    oom_killed: false,
    restart_count: 4,
    finished_at: "2026-11-01T10:00:00Z",
  } as unknown as WatchedInstanceRead;
  expect(instanceReason(crashed, now)).toBe(
    "Exited with code 137 · 2 h ago. Code 137 means the container was killed, often because it ran out of memory." +
      " Docker restarted it 4 times.",
  );
  expect(gpuLabel(["0", "1", "2", "3"])).toBe("0–3");
});
