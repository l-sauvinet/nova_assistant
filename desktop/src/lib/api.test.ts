import { afterEach, describe, expect, it, vi } from "vitest";
import { createApi, ENGINE_UNREACHABLE } from "./api";

describe("api", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("explains in plain French when the engine cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const api = createApi({ port: 9, token: "t" });
    await expect(api.listFolder("/mnt/c")).rejects.toThrow(ENGINE_UNREACHABLE);
    await expect(api.upload(new File(["x"], "a.txt"))).rejects.toThrow(ENGINE_UNREACHABLE);
  });

  it("shows the engine's own error message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Accès refusé à /root" }), { status: 400 })));
    await expect(createApi({ port: 9, token: "t" }).listFolder("/root")).rejects.toThrow("Accès refusé à /root");
  });
});
