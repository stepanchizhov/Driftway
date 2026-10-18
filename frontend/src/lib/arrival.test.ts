import { describe, expect, it } from "vitest";
import { arrivalDate, leaveBy, minutesUntil, suggestedArrival } from "./arrival";

const at = (h: number, m: number) => new Date(2026, 9, 18, h, m, 0, 0);

describe("arriving by a time", () => {
  it("counts the minutes until it", () => {
    expect(minutesUntil("10:55", at(10, 10))).toEqual({ minutes: 45, problem: null });
  });

  it("is tomorrow just after midnight", () => {
    expect(minutesUntil("00:30", at(23, 30))).toEqual({ minutes: 60, problem: null });
    expect(arrivalDate("00:30", at(23, 30))?.getDate()).toBe(19);
  });

  it("says a time has passed rather than planning a day ahead", () => {
    const r = minutesUntil("10:55", at(11, 5));
    expect(r.problem).toMatch(/has passed/);
  });

  it("refuses too soon and too far", () => {
    expect(minutesUntil("10:13", at(10, 10)).problem).toMatch(/too soon/);
    expect(minutesUntil("18:00", at(10, 10)).problem).toMatch(/more than 4 hours/);
  });

  it("refuses something that isn't a time", () => {
    expect(minutesUntil("", at(10, 10)).problem).toBe("Choose a time.");
    expect(minutesUntil("25:00", at(10, 10)).problem).toBe("Choose a time.");
  });

  it("suggests about 45 minutes ahead, on the five", () => {
    expect(suggestedArrival(at(10, 12))).toBe("11:00");
    expect(suggestedArrival(at(23, 40))).toBe("00:25");
  });

  it("works out when to set off", () => {
    expect(leaveBy(at(10, 55), 37.6).getMinutes()).toBe(17);
  });
});
