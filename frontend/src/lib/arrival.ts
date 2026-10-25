// Planning a drive by when it must arrive (founder, 18 Oct 2026: "when we
// are driving to swimming lessons, we need to be there at 10.55"). The time
// is turned into minutes from now when the drive is planned; the server
// keeps every drive within them (arrive_by).

/** The longest drive the server plans, and the shortest. */
export const MAX_MINUTES = 240;
export const MIN_MINUTES = 5;

/** "10:55" as the next 10:55 to come: today, or tomorrow once it has
 *  passed (a 23:30 plan for half past midnight). */
export function arrivalDate(hhmm: string, now: Date): Date | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm.trim());
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  if (h > 23 || min > 59) return null;
  const d = new Date(now);
  d.setHours(h, min, 0, 0);
  if (d.getTime() <= now.getTime()) d.setDate(d.getDate() + 1);
  return d;
}

export interface Arrival {
  /** Whole minutes from now until then, rounded down. */
  minutes: number;
  /** Why no drive can be planned for it, or null. */
  problem: string | null;
}

export function minutesUntil(hhmm: string, now: Date): Arrival {
  const at = arrivalDate(hhmm, now);
  if (!at) return { minutes: 0, problem: "Choose a time." };
  const minutes = Math.floor((at.getTime() - now.getTime()) / 60000);
  if (minutes < MIN_MINUTES) {
    return { minutes, problem: "That's too soon for a drive. Choose a later time." };
  }
  if (minutes > MAX_MINUTES) {
    // Earlier today, by less than a few hours: it has passed, rather than
    // being tomorrow.
    const today = new Date(at);
    today.setDate(today.getDate() - 1);
    const passed = now.getTime() - today.getTime() < 12 * 3600 * 1000;
    return {
      minutes,
      problem: passed
        ? `${clock(today)} has passed. Choose a later time.`
        : "That's more than 4 hours away. Drives go up to 4 hours.",
    };
  }
  return { minutes, problem: null };
}

/** A time of day as the phone shows times. */
export function clock(d: Date): string {
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** A first suggestion: about 45 minutes from now, on the next five. */
export function suggestedArrival(now: Date): string {
  const d = new Date(now.getTime() + 45 * 60000);
  const rounded = Math.ceil(d.getMinutes() / 5) * 5;
  d.setMinutes(rounded, 0, 0);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** When to set off for a drive of `minutes` to arrive by `at`. */
export function leaveBy(at: Date, minutes: number): Date {
  return new Date(at.getTime() - Math.round(minutes) * 60000);
}

/** What a drive's card says about time, planning by an arrival time:
 *  when to leave; once that has passed, when it would arrive if started now;
 *  once started, when it arrives from when it set off (founder, 25 Oct 2026:
 *  the card said "arrives about 12:08" in red after he had arrived). */
export function arrivalTag(
  arriveAt: number,
  minutes: number,
  now: number,
  startedAt: number | null = null,
): { text: string; tone: "ok" | "warn" } {
  const drive = Math.round(minutes) * 60000;
  if (startedAt != null) {
    const at = startedAt + drive;
    return { text: `arrives about ${clock(new Date(at))}`, tone: at > arriveAt + 60000 ? "warn" : "ok" };
  }
  const leave = leaveBy(new Date(arriveAt), minutes);
  if (leave.getTime() < now - 30000) {
    return { text: `arrives about ${clock(new Date(now + drive))}`, tone: "warn" };
  }
  return { text: `leave by ${clock(leave)}`, tone: "ok" };
}
