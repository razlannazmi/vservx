import { expect, test } from "vitest";
import { slugify, withSlugs } from "./slug";

test("a name becomes an address", () => {
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
