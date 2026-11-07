import { expect, test } from "vitest";
import {
  classifyResponse,
  type InstanceState,
  type ServerRead,
  type WatchedInstanceRead,
  type WatchSummaryRead,
  type WorkspaceOverviewRead,
} from "./api/client";
import { clockTime } from "./format";
import { CHAIN_LOOP_MS, CHAIN_STEPS, chainScene, containerStep, HOPS, hopStep, untilNextChange } from "./hops";
import { easeInOut, easeOut } from "./motion";
import { memoryLabel, overviewCard } from "./overview";
import { serverStatus } from "./servers";
import { slugify, withSlugs } from "./slug";
import {
  cardStatus,
  changedStates,
  gpuLabel,
  gpuMemoryPercent,
  instanceReason,
  matchesFilter,
  matchesQuery,
} from "./watch";
import { DEFAULT_ICON, iconName, WORKSPACE_ICONS } from "./workspace-icons";

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
    label: "1 crashed · 5 instances · 1 starting",
  });
  // Problems lead (the card truncates), and stopped containers count in the total but aren't listed.
  expect(
    cardStatus(server, sum("connected", { ready: 8, crashed: 1, not_responding: 1, starting: 1, stopped: 3 })).label,
  ).toBe("1 crashed · 1 not responding · 14 instances · 1 starting");
  expect(cardStatus(server, sum("connected", { ready: 2, stopped: 2 }))).toEqual({ tone: "ok", label: "4 instances" });
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

test("a GPU's bar follows its memory, not its compute", () => {
  // vLLM holds 43 of 45 GB while idle: the bar should be nearly full even at 0% compute.
  expect(gpuMemoryPercent({ memory_used_mib: 43 * 1024, memory_total_mib: 45 * 1024 })).toBeCloseTo(95.6, 1);
  expect(gpuMemoryPercent({ memory_used_mib: null, memory_total_mib: 45 * 1024 })).toBeNull();
  expect(gpuMemoryPercent({ memory_used_mib: 0, memory_total_mib: 0 })).toBeNull();
});

test("long instance lists filter by state chip and search words", () => {
  const instance = (name: string, state: WatchedInstanceRead["state"], model: string | null = null, port = 8000) =>
    ({ name, state, model, port }) as WatchedInstanceRead;
  expect(matchesFilter(instance("a", "crashed"), "attention")).toBe(true);
  expect(matchesFilter(instance("a", "unreachable"), "attention")).toBe(true);
  expect(matchesFilter(instance("a", "starting"), "attention")).toBe(false);
  expect(matchesFilter(instance("a", "stopped"), "stopped")).toBe(true);
  expect(matchesFilter(instance("a", "ready"), "stopped")).toBe(false);
  expect(matchesFilter(instance("a", "paused"), "all")).toBe(true);

  const qwen = instance("vllm-qwen", "ready", "Qwen/Qwen2.5-72B-Instruct", 8003);
  expect(matchesQuery(qwen, "")).toBe(true);
  expect(matchesQuery(qwen, "QWEN 72b")).toBe(true);
  expect(matchesQuery(qwen, "8003")).toBe(true);
  expect(matchesQuery(qwen, "llama")).toBe(false);
});

test("motion curves match their CSS cubic-beziers", () => {
  expect(easeOut(0)).toBe(0);
  expect(easeOut(1)).toBe(1);
  expect(easeOut(0.25)).toBeCloseTo(0.7754, 3);
  expect(easeOut(0.5)).toBeCloseTo(0.966, 3);
  expect(easeInOut(0.25)).toBeCloseTo(0.0529, 3);
  expect(easeInOut(0.5)).toBeCloseTo(0.596, 3);
  expect(easeInOut(0.75)).toBeCloseTo(0.9563, 3);
});

test("the sign-in chain lights one thing at a time, fades, then starts over", () => {
  // Every moment the timer wakes for, across one loop.
  const seen = [];
  for (let t = 0; t < CHAIN_LOOP_MS; t += untilNextChange(t)) seen.push(chainScene(t));
  expect(seen).toEqual([
    { lit: 0, shown: false },
    ...Array.from({ length: CHAIN_STEPS + 1 }, (_, lit) => ({ lit, shown: true })),
    { lit: CHAIN_STEPS, shown: false },
  ]);
  expect(chainScene(CHAIN_LOOP_MS + 1)).toEqual(chainScene(1));
  // The containers turn up only once the last hop has lit.
  expect(containerStep(0)).toBeGreaterThan(hopStep(HOPS.length - 1));
});

test("only an instance whose state changed since the last poll flashes", () => {
  const last = new Map<string, InstanceState>([
    ["a", "ready"],
    ["b", "ready"],
  ]);
  const now = [
    { name: "a", state: "crashed" as const },
    { name: "b", state: "ready" as const },
    { name: "c", state: "starting" as const },
  ];
  expect(changedStates(last, now)).toEqual(["a"]);
  expect(changedStates(new Map(), now)).toEqual([]);
});

test("an unknown or missing icon falls back to the default", () => {
  expect(iconName(null)).toBe(DEFAULT_ICON);
  expect(iconName("no-such-icon")).toBe(DEFAULT_ICON);
  expect(WORKSPACE_ICONS.every((icon) => iconName(icon.name) === icon.name)).toBe(true);
  expect(WORKSPACE_ICONS.some((icon) => icon.name === DEFAULT_ICON)).toBe(true);
  expect(WORKSPACE_ICONS.length).toBeGreaterThanOrEqual(24);
  // Icons the app already uses for something else (Workspaces heading, mode toggle, settings gear) aren't offered.
  expect(WORKSPACE_ICONS.filter((icon) => ["layers", "sun", "cog", "settings"].includes(icon.name))).toEqual([]);
});

const ov = (servers: object, instances = {}, gpus: object | null = null, models: string[] = []) =>
  ({
    workspace_id: 1,
    servers: { total: 0, up: 0, not_tested: 0, unreachable: 0, trouble: 0, docker_problem: 0, ...servers },
    instances,
    gpus,
    models,
  }) as unknown as WorkspaceOverviewRead;

test("workspace card lines", () => {
  expect(overviewCard(undefined, false).checking).toBe(true);
  expect(overviewCard(undefined, true).empty).toBe(true); // created since the last poll
  expect(overviewCard(ov({}), true).empty).toBe(true);
  const servers = (s: object) => overviewCard(ov(s), true).servers;
  expect(servers({ total: 3, up: 3 })).toEqual({ tone: "ok", label: "3 servers up" });
  expect(servers({ total: 1, up: 1 })?.label).toBe("1 server up");
  expect(servers({ total: 4, up: 3, not_tested: 1 })).toEqual({ tone: "ok", label: "3 of 4 servers up" });
  expect(servers({ total: 2, up: 1, unreachable: 1, trouble: 1 })).toEqual({ tone: "bad", label: "1 of 2 unreachable" });
  expect(servers({ total: 3, up: 1, trouble: 1, docker_problem: 1 })).toEqual({ tone: "bad", label: "2 of 3 need attention" });
  expect(servers({ total: 2, up: 1, docker_problem: 1 })).toEqual({ tone: "warn", label: "1 of 2 need attention" });
  expect(servers({ total: 2, not_tested: 2 })).toEqual({ tone: "none", label: "not tested yet" });
  expect(servers({ total: 2 })).toEqual({ tone: "none", label: "checking…" });

  const full = overviewCard(
    ov({ total: 1, up: 1 }, { ready: 5, crashed: 1, starting: 1 }, { count: 8, memory_used_mib: 217088, memory_total_mib: 393216 }, [
      "meta-llama/Llama-3.1-70B",
      "Qwen/Qwen2.5-32B",
      "a/b",
      "c/d",
    ]),
    true,
  );
  expect(full.instances).toEqual({ tone: "bad", label: "1 crashed · 7 instances · 1 starting" });
  expect(full.gpus?.label).toBe("8 GPUs");
  expect(full.gpus?.memory).toBe("212 / 384 GiB");
  expect(full.gpus?.percent).toBeCloseTo(55.2, 1);
  expect(full.models).toBe("Llama-3.1-70B · Qwen2.5-32B · +2");
  expect(memoryLabel(1677722, 1992294)).toBe("1.6 / 1.9 TiB");
  const bare = overviewCard(ov({ total: 1, up: 1 }, {}, { count: 2, memory_used_mib: null, memory_total_mib: null }), true);
  expect(bare.gpus).toEqual({ label: "2 GPUs", memory: null, percent: null });
  expect([bare.instances, bare.models]).toEqual([null, null]);
  expect(overviewCard(ov({ total: 1, up: 1 }), true).gpus).toBeNull();
});
