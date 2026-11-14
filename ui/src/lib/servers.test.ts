import { expect, test } from "vitest";
import { instanceOrigin, serverAddress } from "$lib/servers";

test("serverAddress", () => {
  expect(serverAddress({ kind: "this_machine", username: null, host: null, port: 22 })).toBe("This machine");
  expect(serverAddress({ kind: "ssh", username: "u", host: "h", port: 22 })).toBe("u@h:22");
});

test("instanceOrigin", () => {
  expect(instanceOrigin({ source: "systemd", name: "v.service", image: "" })).toBe("systemd · v.service");
  expect(instanceOrigin({ source: "systemd-user", name: "v.service", image: "" })).toBe("systemd --user · v.service");
  expect(instanceOrigin({ source: "docker", name: "v", image: "vllm/vllm-openai" })).toBe("vllm/vllm-openai");
});
