/**
 * Which Driftway this is, and what changed in each version.
 *
 * Founder request, 10 Oct 2026: the founder and testers need to know which
 * version they are using. The newest release comes first; its number is the
 * app's version, shown in Settings with the build (the commit it was built
 * from) and the server's own version and build. The server's number lives in
 * backend/core/version.py, and a test fails if the two differ, so a release
 * bumps both.
 *
 * Versions before 0.7.0 were never shown in the app. They were numbered
 * afterwards from the project history: the commits themselves only carry
 * "v.0.2.2" and "v.0.3". Project Bible document versions (v0.4, v0.5,
 * v0.6.0) are a separate numbering and are not these.
 */

export interface Release {
  version: string;
  /** When it was released, or the span of days it was built over. */
  date: string;
  /** What changed, in words a parent would use. */
  changes: string[];
  /** Numbered afterwards from the project history. */
  retroactive?: boolean;
}

export const RELEASES: Release[] = [
  {
    version: "0.7.0",
    date: "10 Oct 2026",
    changes: [
      "Choose a walk's checkpoint on the map, as well as by searching for it.",
      "New walk preference: how close a walk must come to your checkpoint. Pass a statue on a hill at a distance instead of climbing up to it.",
      "If the nearest path is away from your checkpoint, both are shown and you're asked before it's used. You're told when a checkpoint can't be reached, or is too far for the time you chose.",
      "Greener and Quieter now reach the route provider in the form it accepts. A walk says when the provider has no data to make a difference, as around Windsor.",
      "When the route provider's daily limit is reached, the Walk tab says so, instead of saying a place can't be reached.",
      "Drives try not to use the same road twice: fewer turn-arounds in testing.",
      "This version history, and the version and build shown in Settings.",
    ],
  },
  {
    version: "0.6",
    date: "7–9 Oct 2026",
    retroactive: true,
    changes: [
      "Walk tab (closed beta): walks for a pram, a carrier or just you, with surfaces, steps, gates and slopes, and where each fact comes from.",
      "Curated walks around Windsor and in Berlin, and walks made from wherever you are.",
      "Walks fitted to the time you choose, from 10 minutes to 4 hours, with the turning point marked.",
      "Walk preferences: how much you mind walking the same path twice, greener or quieter, walks that need travel.",
      "Walks through a checkpoint, up to three different ones.",
      "Each walk on a map, and in Google Maps through three points.",
      "Still Asleep says it opens Google Maps before it does.",
    ],
  },
  {
    version: "0.5",
    date: "14 Sep 2026",
    retroactive: true,
    changes: [
      "Accounts by invitation, for the closed beta.",
      "Saved drives belong to your account, and you can download or delete your data.",
      "Limits on how many routes can be asked for at once, so the service stays up for everyone.",
      "Old meetups and long-inactive accounts can be cleared automatically.",
    ],
  },
  {
    version: "0.4",
    date: "10–11 Sep 2026",
    retroactive: true,
    changes: [
      "Three jobs at the bottom of the screen: Still Asleep, Plan a drive, Meet up.",
      "Drives that end somewhere else, arriving after the time you need.",
      "Meet Halfway: two parents, private starting points, one place you agree on.",
      "The hand-off to navigation apps says what each one can follow.",
      "Keeps working when the database is briefly unreachable.",
    ],
  },
  {
    version: "0.3",
    date: "5 Jul 2026",
    retroactive: true,
    changes: ["Small fixes to the quick drive home."],
  },
  {
    version: "0.2.2",
    date: "26 Jun 2026",
    retroactive: true,
    changes: [
      "Saved places and favourite drives.",
      "Drives to a destination, padded to the time you need.",
      "A quick drive home.",
    ],
  },
  {
    version: "0.1",
    date: "25 Jun 2026",
    retroactive: true,
    changes: [
      "Driftway alpha: circular drives of the length you choose, three to pick from, started in Google Maps.",
    ],
  },
];

export const APP_VERSION = RELEASES[0].version;

/** The commit this app was built from, set at build time; "dev" locally. */
export const BUILD: string = typeof __BUILD_COMMIT__ === "string" ? __BUILD_COMMIT__ : "dev";
