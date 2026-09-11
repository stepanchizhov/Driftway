/**
 * Tunable rules for Still Asleep target suggestions.
 *
 * Kept in one place, out of component logic, because these are product
 * hypotheses that will move with field data — Bible v0.4 §6 asks for exactly
 * that. Changing a nap-window guess should not mean editing a React component.
 */

/**
 * How long a destination the parent merely *searched for* stays on offer.
 *
 * HYPOTHESIS (Bible v0.4 §6): about six hours. This replaces the earlier
 * seven-day quick-action hypothesis, which was far too generous — a place
 * visited on Tuesday should not be the app's suggestion on Sunday.
 *
 * The reasoning is that Still Asleep is for *this* outing: you drove to the
 * pool, the baby fell asleep on the way out, and you want a longer way home.
 * Six hours covers that. It does not cover "somewhere I looked at last week".
 */
export const RECENT_WINDOW_HOURS = 6;

/**
 * Hard ceiling regardless of the window above.
 *
 * A destination never survives past this unless the parent explicitly saved
 * it. Saving is the signal that a place matters beyond one outing; an
 * unsaved search is not.
 */
export const RECENT_ABSOLUTE_MAX_HOURS = 24;

export const RECENT_WINDOW_MS = RECENT_WINDOW_HOURS * 60 * 60 * 1000;
export const RECENT_ABSOLUTE_MAX_MS = RECENT_ABSOLUTE_MAX_HOURS * 60 * 60 * 1000;

/**
 * Durations offered on the urgent screen.
 *
 * Shorter than the planner's range on purpose: Still Asleep is reached with a
 * sleeping child in the back and seconds to act. Ninety minutes is a planning
 * decision, not an urgent one, and belongs in Plan a drive.
 */
export const STILL_ASLEEP_DURATIONS = [15, 30, 45, 60] as const;

/** Tolerance used when the parent has not chosen one. */
export const STILL_ASLEEP_DEFAULT_TOLERANCE = 10;

/**
 * Is this remembered destination still worth offering?
 *
 * `explicitlySaved` exempts a place from the recency window entirely — that is
 * what saving means.
 */
export function isRecentEnough(
  savedAt: number,
  opts: { explicitlySaved?: boolean; now?: number } = {},
): boolean {
  const now = opts.now ?? Date.now();
  const age = now - savedAt;
  if (age < 0) return false; // a clock skew or a doctored value; treat as stale
  if (opts.explicitlySaved) return age <= RECENT_ABSOLUTE_MAX_MS;
  return age <= RECENT_WINDOW_MS;
}
