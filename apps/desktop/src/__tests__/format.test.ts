import { describe, expect, it } from "vitest";
import { dateTime, seconds, spokenDuration, usd } from "../lib/format";

describe("format", () => {
  it("affiche les dollars a la francaise", () => {
    expect(usd(0.35).replace(/\s/g, " ")).toBe("0,35 $");
    expect(usd(null)).toBe("tarif inconnu");
  });
  it("affiche les secondes", () => {
    expect(seconds(2.5)).toBe("2,5 s");
  });
  it("estime la duree parlee a 2,5 mots par seconde", () => {
    expect(spokenDuration("un deux trois quatre cinq")).toBe(2);
  });
  it("lit les dates UTC sans fuseau", () => {
    expect(dateTime(null)).toBe("—");
    expect(dateTime("2026-11-15T10:00:00")).toMatch(/15\/11\/2026/);
  });
});
