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
 *
 * Founder request, 11 Oct 2026: smaller steps. What shipped after 0.7.0 as
 * "0.8.0, in progress" was split by when it was built (0.7.1 to 0.8.3,
 * numbered afterwards), and 0.4 and 0.6 were split the same way from their
 * commit dates. Each release gets its own entry when it is pushed, not one
 * growing list.
 *
 * Numbering (founder, 11 Oct 2026): the middle number moves only for a
 * conceptual shift in what Driftway is - 0.6 brought walks, 0.8 made it ready
 * for outside testers - and so will 1.0. Everything else, new features that
 * grow what exists as well as fixes, moves the last number.
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
    version: "0.8.14",
    date: "13 Oct 2026",
    changes: [
      "Roadworks on a drive card are only those actually under way now, not ones merely planned or applied for.",
      "Roadworks in Wales, Scotland and Northern Ireland too, from TomTom's traffic reports, and motorway works in England that Street Manager doesn't carry.",
      "Distances in a walk's notes follow your units (miles or kilometres), and \"after 0 yd\" reads \"at the start\".",
    ],
  },
  {
    version: "0.8.13",
    date: "13 Oct 2026",
    changes: [
      "Drives try to go round the busiest stretch of speed bumps, traffic lights and roadworks, using waypoints Google Maps follows too.",
      "A turn-around now counts like a speed bump, less than a red light: a drive with many fewer bumps and lights can go first even with a turn-around.",
      "Where a drive has to turn round, it does so at a roundabout, a turning circle or a loop at the end of a street when there's one nearby, and the card says where.",
      "When openrouteservice, the map service walks are made with, is struggling, walks come from TomTom's walking routes instead (not pram walks), and the screen says what's wrong and what still works, with Try again. No more long waits for a bare error.",
    ],
  },
  {
    version: "0.8.12",
    date: "12 Oct 2026",
    changes: [
      "Ready for live roadworks in England: once Street Manager's feed is switched on, drive cards list temporary traffic lights, stop/go boards and closures on the way today, and a drive without them is preferred when it's as good otherwise.",
    ],
  },
  {
    version: "0.8.11",
    date: "12 Oct 2026",
    changes: [
      "Drives count the traffic lights mapped along them, around Windsor for now: junctions and pedestrian-operated crossings apart. A drive with fewer lights and bumps is offered first when it's as good otherwise.",
      "Miles by default in the UK. Kilometres elsewhere, and your own choice in Settings always wins.",
    ],
  },
  {
    version: "0.8.10",
    date: "12 Oct 2026",
    changes: [
      "Long trails near you, in sections: a ring round a city park or a long-distance path is offered as walks of a few kilometres there and back, turning back when your time is up.",
    ],
  },
  {
    version: "0.8.9",
    date: "11 Oct 2026",
    changes: [
      "Walks for anywhere: where Driftway has no curated walks yet, the Walk tab lists the trails mapped near you right away and asks for checked walks for your area, which usually follow within a day. Only a rough area, about 10 km across, is sent (privacy policy 1.7).",
      "Some walks have a short description written with AI from the walk's own map data. Each is checked by us before it's shown, and says so.",
    ],
  },
  {
    version: "0.8.8",
    date: "11 Oct 2026",
    changes: [
      "Seven more curated walks, from trails mapped on OpenStreetMap: the Cliveden Blue, Green and Gold trails, the Cookham Wetland and Wildlife Trail, Runnymede's Summer and Views routes, and the St Ann's Hill circular. Each is checked for your pram or carrier like every other walk, and links to its operator's page.",
    ],
  },
  {
    version: "0.8.7",
    date: "11 Oct 2026",
    changes: [
      "Drives count the speed bumps mapped along them, around Windsor for now, and say \"About N speed bumps mapped\". A drive with fewer is offered first when it's as good otherwise: no extra turn-arounds, and within 3 minutes of the time.",
    ],
  },
  {
    version: "0.8.6",
    date: "11 Oct 2026",
    changes: [
      "Android's Back button no longer closes the app from anywhere: it closes Saved, Settings and drive results, then returns to Still asleep, and only leaves the app from there.",
      "A recorded walk that ends short of where it started can be walked as a loop: importing asks, and My walks has \"Make it a loop\".",
    ],
  },
  {
    version: "0.8.5",
    date: "11 Oct 2026",
    changes: [
      "Saved places: keep Home and anywhere else you go often, under ★ Saved. They're one tap away in Still asleep and wherever you search for a place, and stay on this phone (privacy policy 1.6).",
      "Removing Home asks first and leaves no Home, rather than quietly treating another place as Home.",
      "My walks shows your own route on the map next to the walk Driftway follows, and says where they differ.",
    ],
  },
  {
    version: "0.8.4",
    date: "11 Oct 2026",
    changes: [
      "My walks: draw a route you actually walk, import one from a GPX file, or save a walk Driftway made. It's checked for your pram or carrier, time and pace, and kept on your phone only (privacy policy 1.5).",
      "Your own walking pace, in Walk preferences: walk times, and how long walks made from your start are, follow it.",
      "Walks work for everyone, without signing in, and accounts no longer need an invitation (privacy policy 1.4).",
    ],
  },
  {
    version: "0.8.3",
    date: "11 Oct 2026",
    retroactive: true,
    changes: [
      "Location never blocks the app: after 12 seconds Driftway says why, and you can search where you are instead, in Still asleep too. A position that arrives later still counts.",
    ],
  },
  {
    version: "0.8.2",
    date: "11 Oct 2026",
    retroactive: true,
    changes: [
      "Walks can go through up to three checkpoints, in the order you add them, then home another way. Drop pins on the map or search for places.",
      "How close a walk must come now applies to every checkpoint, not only the last: a statue up a dead end is passed, not climbed.",
      "Walks made for you fit your time better: one that misses by more than 15% is asked for again, and walks within about 20% of your time always come first.",
      "Dead-end detours, out along a path and straight back, are cut out of walks made for you.",
      "The Walk tab makes walks as soon as it knows where you are starting, and says what's missing instead of greying out the button.",
    ],
  },
  {
    version: "0.8.1",
    date: "11 Oct 2026",
    retroactive: true,
    changes: [
      "A new app icon, chosen by the family: a road looping round the moon and back home, under the stars. It's easier to read and to find on a home screen.",
    ],
  },
  {
    version: "0.8.0",
    date: "10 Oct 2026",
    retroactive: true,
    changes: [
      "A Feedback button at the top of every screen. It says which screen you were on and which version you have, and can say what you were doing just before.",
      "A privacy policy, a guide for testers, and a page on deleting your account without the app, all linked from Settings.",
      "You can download or delete your account even if it has been disabled. No invitation is needed.",
      "Driftway's server logs no longer record what you search for, your position, or the private part of meetup links.",
      "Pram walks always keep pram routing. Greener and Quieter are no longer offered with a pram: they used walking routes that dropped the pram's rules on surface, slope and kerbs.",
      "A site icon, and an iPhone home-screen icon without black corners. The app description now includes walks and meetups.",
      "Ready for Driftway's new address: the old one says so, and what does and doesn't come with you.",
      "The app no longer keeps a growing copy of every map image you've seen.",
      "Driftway's typefaces now come with the app, so your phone no longer contacts Google Fonts.",
      "Feedback sent without an account is deleted after a year. Before, it had no time limit.",
      "Settings describes what Driftway does now, and what's planned, without promising dates.",
    ],
  },
  {
    version: "0.7.1",
    date: "10 Oct 2026",
    retroactive: true,
    changes: [
      "Walks can be made again: the route provider had moved to a new address.",
      "When the route provider refuses to make walks, the Walk tab says so, instead of saying a place can't be reached.",
      "If our usual route provider stops answering, drives, Meet Halfway and place search carry on with a stand-in, and say their times have no live traffic.",
    ],
  },
  {
    version: "0.7.0",
    date: "10 Oct 2026",
    changes: [
      "Choose a walk's checkpoint on the map, as well as by searching for it.",
      "New walk preference: how close a walk must come to your checkpoint. Pass a statue on a hill at a distance instead of climbing up to it.",
      "If the nearest path is away from your checkpoint, both are shown and you're asked before it's used. You're told when a checkpoint can't be reached, or is too far for the time you chose.",
      "Greener and Quieter now reach the route provider in the form it accepts. A walk says when the provider has no data to make a difference, as around Windsor.",
      "Drives try not to use the same road twice: fewer turn-arounds in testing.",
      "This version history, and the version and build shown in Settings.",
    ],
  },
  {
    version: "0.6.2",
    date: "9 Oct 2026",
    retroactive: true,
    changes: [
      "Walks made from wherever you are, as well as the curated ones.",
      "Walks through a checkpoint, out one way and back another, up to three different ones.",
      "Walk preferences: how much you mind walking the same path twice, greener or quieter, walks that need travel.",
      "A third way to go: Just me, for walking without a pram or a carrier.",
      "Each walk on a map, grouped by whether it starts at your door, and in Google Maps through three points.",
    ],
  },
  {
    version: "0.6.1",
    date: "9 Oct 2026",
    retroactive: true,
    changes: [
      "Walk becomes a tab, and you can sign in from where you are.",
      "Walks fitted to the time you choose, from 10 minutes to 4 hours, with the turning point marked.",
      "More curated walks: in Windsor, and in Berlin. Place search works outside the UK.",
    ],
  },
  {
    version: "0.6.0",
    date: "8 Oct 2026",
    retroactive: true,
    changes: [
      "Walks (closed beta): curated walks around Windsor for a pram or a carrier, with surfaces, steps, gates and slopes, and where each fact comes from.",
    ],
  },
  {
    version: "0.5.1",
    date: "7–8 Oct 2026",
    retroactive: true,
    changes: [
      "Still Asleep says it opens Google Maps before it does.",
      "Driftway notices when its database comes back, instead of needing a restart.",
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
    version: "0.4.1",
    date: "11 Sep 2026",
    retroactive: true,
    changes: [
      "Three jobs at the bottom of the screen: Still Asleep, Plan a drive, Meet up.",
      "The hand-off to navigation apps says what each one can follow.",
    ],
  },
  {
    version: "0.4",
    date: "10 Sep 2026",
    retroactive: true,
    changes: [
      "Drives that end somewhere else, arriving after the time you need.",
      "Meet Halfway: two parents, private starting points, one place you agree on.",
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

/**
 * Which channel this build is (11 Oct 2026, docs/CHANNELS.md): "next" is the
 * latest build, for closed testing at next.driftway.stepan.chizhov.com, set
 * with VITE_CHANNEL=next on that site. Everything else is the stable app.
 */
export const CHANNEL: "stable" | "next" =
  (import.meta.env.VITE_CHANNEL ?? "").trim().toLowerCase() === "next" ? "next" : "stable";
export const APP_NAME = CHANNEL === "next" ? "Driftway Next" : "Driftway";
/** The version sent with feedback, so a report says which channel it came
 *  from: "0.8.0", or "0.8.0-next". */
export const REPORTED_VERSION = CHANNEL === "next" ? `${APP_VERSION}-next` : APP_VERSION;
