import { describe, expect, it } from "vitest";
import { greetingFor } from "./greeting";

describe("greetingFor", () => {
  it("says Bonjour during the day and Bonsoir in the evening", () => {
    expect(greetingFor(new Date(2026, 8, 29, 9))).toBe("Bonjour");
    expect(greetingFor(new Date(2026, 8, 29, 17, 59))).toBe("Bonjour");
    expect(greetingFor(new Date(2026, 8, 29, 18))).toBe("Bonsoir");
    expect(greetingFor(new Date(2026, 8, 29, 2))).toBe("Bonsoir");
  });
});
