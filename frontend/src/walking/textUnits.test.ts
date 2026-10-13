import { describe, expect, it } from "vitest";
import { alongText, metresInText } from "./textUnits";

describe("distances in the server's sentences", () => {
  it("become miles or yards when miles are chosen", () => {
    expect(metresInText("Surface not recorded for about 4500 m.", "mi")).toBe(
      "Surface not recorded for about 2.8 mi.",
    );
    expect(metresInText("A gate about 120 m in.", "mi")).toBe("A gate about 130 yd in.");
  });

  it("become kilometres when long, and stay metres when short", () => {
    expect(metresInText("about 4500 m in total.", "km")).toBe("about 4.5 km in total.");
    expect(metresInText("steps for 30 m", "km")).toBe("steps for 30 m");
  });

  it("leave other words alone", () => {
    expect(metresInText("Made 3 min ago from my map", "mi")).toBe("Made 3 min ago from my map");
  });

  it("say 'at the start' rather than 'after 0'", () => {
    expect(alongText(0, "mi")).toBe("at the start");
    expect(alongText(500, "mi")).toBe("after 547 yd");
    expect(alongText(505, "km")).toBe("after 510 m");
  });
});
