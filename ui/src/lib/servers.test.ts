import { expect, test } from "vitest";
import type { ServerRead } from "./api/client";
import { serverStatus } from "./servers";

const at = new Date("2026-10-31T12:00:00Z");
// The rest of a server doesn't matter here.
const base = { id: 1, name: "gpu-1", host: "10.0.0.1", port: 22, username: "ubuntu" };
const s = (last_test: unknown) => ({ ...base, last_test }) as unknown as ServerRead;

test("status follows the latest test", () => {
  expect(serverStatus(s(null), at)).toEqual({ tone: "none", label: "never tested" });
  expect(serverStatus(s({ ok: true, at: "2026-10-31T11:55:00Z" }), at)).toEqual({ tone: "ok", label: "OK · tested 5 min ago" });
  expect(serverStatus(s({ ok: false, failure: "host_key_changed", at: "2026-10-31T11:00:00Z" }), at).tone).toBe("warn");
  expect(serverStatus(s({ ok: false, failure: "unreachable", at: "2026-10-31T11:40:00Z" }), at)).toEqual({
    tone: "bad",
    label: "unreachable · 20 min ago",
  });
});
