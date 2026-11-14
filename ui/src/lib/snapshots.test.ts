import { describe, expect, it, vi } from "vitest";
import { changedLabel, copyText, drawerSearch, lineDiff, readDrawer, type DrawerState } from "./snapshots";

describe("snapshots", () => {
  it("keeps drawer state in the address", () => {
    const states: DrawerState[] = [
      { view: "server", instance: null, at: null, compare: null },
      { view: "instance", instance: { source: "docker", name: "vllm-qwen" }, at: 12, compare: null },
      { view: "instance", instance: { source: "docker", name: "all" }, at: null, compare: [3, 9] },
      { view: "instance", instance: { source: "systemd-user", name: "vllm.service" }, at: null, compare: null },
    ];
    for (const state of states) expect(readDrawer(drawerSearch(state))).toEqual(state);
    expect(drawerSearch(null)).toBe("");
    expect(readDrawer("?other=1")).toBeNull();
  });
  it("tags changes from the last 24 hours only", () => {
    const now = new Date("2026-11-07T15:00:00");
    expect(changedLabel("2026-11-07T14:32:00", now)).toMatch(/^changed \d/);
    expect(changedLabel("2026-11-06T22:10:00", now)).toMatch(/^changed yesterday /);
    expect(changedLabel("2026-11-06T14:00:00", now)).toBeNull();
    expect(changedLabel(null, now)).toBeNull();
  });
  it("diffs commands line by line", () => {
    expect(lineDiff("a\nb\nc", "a\nB\nc")).toEqual([
      { kind: "same", text: "a" }, { kind: "del", text: "b" }, { kind: "add", text: "B" }, { kind: "same", text: "c" }]);
  });
  it("copies without the clipboard API", async () => {
    const fallback = vi.fn(() => true);
    expect(await copyText("x", undefined, fallback)).toBe(true);
    expect(fallback).toHaveBeenCalledWith("x");
    expect(await copyText("x", { writeText: () => Promise.reject(new Error("denied")) }, () => false)).toBe(false);
  });
});
