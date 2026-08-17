/**
 * Tests for constants/channel.
 *
 * Covers:
 * - CHANNEL_COLORS values are valid color names
 */
import { describe, it, expect } from "vitest";
import { CHANNEL_COLORS } from "./channel";

describe("CHANNEL_COLORS", () => {
  it("covers channels that were previously omitted", () => {
    expect(CHANNEL_COLORS.wechat).toBeTruthy();
    expect(CHANNEL_COLORS.onebot).toBeTruthy();
  });

  it("color values are non-empty strings", () => {
    for (const value of Object.values(CHANNEL_COLORS)) {
      expect(typeof value).toBe("string");
      expect(value.length).toBeGreaterThan(0);
    }
  });
});
