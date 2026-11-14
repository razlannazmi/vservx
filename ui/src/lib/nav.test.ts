import { expect, test } from "vitest";
import type { Route } from "./router.svelte";
import type { Workspace } from "./workspaces.svelte";
import { activeTab, tabTarget, workspacePages } from "./nav";

const ws = (id: number, slug: string, role: Workspace["role"] = "viewer") => ({ id, slug, role, name: slug }) as Workspace;

test("workspacePages: settings only for owners", () => {
  expect(workspacePages(ws(1, "aicoe", "owner")).map((p) => p.href)).toEqual([
    "/workspaces/aicoe",
    "/workspaces/aicoe/keys",
    "/workspaces/aicoe/members",
    "/workspaces/aicoe/settings",
  ]);
  expect(workspacePages(ws(1, "aicoe", "operator")).map((p) => p.name)).toEqual(["servers", "keys", "members"]);
});

test("tabTarget: the route's workspace wins", () => {
  const list = [ws(1, "a"), ws(2, "b")];
  const route: Route = { name: "keys", workspaceSlug: "b" };
  expect(tabTarget(route, list, 1)?.id).toBe(2);
});

test("tabTarget follows the last workspace by id", () => {
  // Renamed since it was visited: same id, new slug.
  const list = [ws(1, "a"), ws(2, "b-renamed")];
  expect(tabTarget({ name: "account" }, list, 2)?.slug).toBe("b-renamed");
});

test("tabTarget: falls back to the first workspace, then none", () => {
  expect(tabTarget({ name: "home" }, [ws(1, "a"), ws(2, "b")], 9)?.id).toBe(1);
  expect(tabTarget({ name: "home" }, [], null)).toBeNull();
});

test("activeTab", () => {
  expect(activeTab({ name: "servers", workspaceSlug: "a", serverId: 3, instance: { source: "docker", name: "x" } })).toBe(
    "servers",
  );
  expect(activeTab({ name: "members", workspaceSlug: "a" })).toBe("members");
  expect(activeTab({ name: "account" })).toBe("you");
  expect(activeTab({ name: "admin-database" })).toBe("you");
  expect(activeTab({ name: "home" })).toBeNull();
});
