import { describe, expect, it, vi } from "vitest";
import { openWithCheck } from "./safeOpen";

describe("openWithCheck", () => {
  it("opens safe files at once without asking", async () => {
    const open = vi.fn().mockResolvedValue({ ok: true });
    const confirm = vi.fn();
    expect(await openWithCheck(open, confirm)).toBe(true);
    expect(open).toHaveBeenCalledExactlyOnceWith(false);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("shows the warning and opens only once the user accepts", async () => {
    const open = vi.fn().mockResolvedValueOnce({ ok: false, warning: "⚠️ programme" }).mockResolvedValueOnce({ ok: true });
    const confirm = vi.fn().mockResolvedValue(true);
    expect(await openWithCheck(open, confirm)).toBe(true);
    expect(confirm).toHaveBeenCalledWith("⚠️ programme");
    expect(open).toHaveBeenLastCalledWith(true);
  });

  it("does not open when the user declines", async () => {
    const open = vi.fn().mockResolvedValue({ ok: false, warning: "⚠️ programme" });
    expect(await openWithCheck(open, vi.fn().mockResolvedValue(false))).toBe(false);
    expect(open).toHaveBeenCalledTimes(1);
  });
});
