import { describe, expect, it } from "vitest";
import { unitsFor } from "./defaultUnits";

describe("default units", () => {
  it("is miles in the UK, whatever the language", () => {
    expect(unitsFor("Europe/London", ["ru-RU"])).toBe("mi");
    expect(unitsFor("Europe/Jersey", ["en-US"])).toBe("mi");
  });
  it("follows the region in the language settings elsewhere", () => {
    expect(unitsFor("America/New_York", ["en-US"])).toBe("mi");
    expect(unitsFor("Europe/Berlin", ["de-DE"])).toBe("km");
    expect(unitsFor("Europe/Dublin", ["en-IE"])).toBe("km");
    expect(unitsFor("Europe/Berlin", ["en-GB"])).toBe("mi");
  });
  it("is km when nothing says otherwise", () => {
    expect(unitsFor(undefined, ["en"])).toBe("km");
    expect(unitsFor("Asia/Tokyo", [])).toBe("km");
  });
});
