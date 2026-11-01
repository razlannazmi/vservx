import { expect, test } from "vitest";
import { classifyResponse } from "./client";

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
