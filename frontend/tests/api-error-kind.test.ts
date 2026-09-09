import { describe, expect, it } from "vitest";
import { kindForStatus } from "@/lib/api";

describe("kindForStatus", () => {
  it("maps 400 to validation (regression: previously fell through to 'server')", () => {
    // Discovered during Phase 10 inspection: the backend already returns
    // 400 for InvalidAlertRuleConfigurationError (Phase 8), but this
    // mapping never accounted for it, so AlertRuleForm showed a generic
    // "server error" message instead of a validation message.
    expect(kindForStatus(400)).toBe("validation");
  });

  it("maps 422 to validation", () => {
    expect(kindForStatus(422)).toBe("validation");
  });

  it("maps 409 to conflict", () => {
    expect(kindForStatus(409)).toBe("conflict");
  });

  it("maps 404 to not_configured", () => {
    expect(kindForStatus(404)).toBe("not_configured");
  });

  it("maps 500+ to server", () => {
    expect(kindForStatus(500)).toBe("server");
    expect(kindForStatus(503)).toBe("server");
  });
});
