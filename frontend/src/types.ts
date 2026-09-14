// Mirrors the backend data contracts in core/models.py.
// Keep these in sync if the backend models change.

export type RoadProfile = "motorway" | "mixed" | "quiet";
export type Direction = "surprise" | "N" | "E" | "S" | "W";

/** Which geometry problem the backend solved. */
export type RouteMode = "loop" | "destination";

/** How precisely a search result names a spot. */
export type PlaceKind =
  | "postcode"
  | "postcode_area"
  | "address"
  | "street"
  | "poi"
  | "place";

/** A location the user explicitly picked from search. Free text is never
 *  routed: an endpoint is either a resolved Place, the device location, or
 *  saved Home. */
export interface Place {
  id: string;
  label: string;
  detail: string;
  coord: Coord;
  kind: PlaceKind;
  /** Area centroid rather than a precise point — offer to refine it. */
  approximate: boolean;
}

export interface SearchResponse {
  query: string;
  places: Place[];
  provider: string;
}

export interface Coord {
  lat: number;
  lng: number;
}

export interface GenerateRequest {
  start: Coord;
  finish?: Coord | null;
  target_minutes: number;
  tolerance_minutes: number;
  road_profile: RoadProfile;
  direction: Direction;
  mode?: RouteMode;
  /** Advisory: never honoured at the cost of the route's shaping points. */
  preferred_navigation?: string | null;
}

export interface RoadMix {
  motorway: number;
  primary: number;
  secondary: number;
  residential: number;
}

/** One navigation app, and whether it can carry this particular route. */
export interface NavigationOption {
  provider_id: string;
  label: string;
  url: string;
  /** True when the app can carry the shaping waypoints. Not a claim that it
   *  reproduces our path or duration - every app recalculates between them. */
  keeps_waypoints: boolean;
  dropped_waypoints: number;
  /** Empty means anywhere; otherwise the platforms it suits. */
  platforms: string[];
  notice?: string | null;
}

export interface RouteOption {
  id: string;
  predicted_minutes: number;
  distance_km: number;
  character: string;
  road_mix: RoadMix;
  score: number;
  delta_minutes: number;
  waypoints: Coord[];
  geometry: Coord[];
  /** Empty string when simulated — there is nothing real to navigate. */
  maps_url: string;
  confidence: "low" | "medium" | "high";
  /** Destination mode: minutes longer than driving straight there. */
  extra_minutes?: number | null;
  /** The plain quickest route, offered when the target was below the floor. */
  is_direct: boolean;
  /** Demo geometry from the simulator. Never navigable. */
  simulated: boolean;
  /** Which quality preference this route misses, if any. */
  caveat?: string | null;
  /** Apps that could drive this, best first. Empty when simulated. */
  navigation: NavigationOption[];
}

export interface GenerateResponse {
  routes: RouteOption[];
  target_minutes: number;
  tolerance_minutes: number;
  generated_at: string;
  provider: string;
  candidates_evaluated: number;
  mode: RouteMode;
  /** Destination mode: the quickest drive between the two points. */
  direct_minutes?: number | null;
  simulated: boolean;
  /** Plain-language explanation when the answer is not what was asked. */
  notice?: string | null;
}

export interface FeedbackRequest {
  route_id: string;
  predicted_minutes: number;
  actual_minutes?: number | null;
  would_use_again?: boolean | null;
  baby_slept?: "yes" | "no" | "unknown" | null;
  notes?: string | null;
  owner?: string | null;
}

export interface FavouriteCreate {
  owner: string;
  label?: string;
  place_label?: string;
  duration_minutes: number;
  distance_km?: number;
  road_profile?: string;
  character?: string;
  maps_url?: string;
}

export interface Favourite {
  /** "account" once it belongs to a signed-in account, "device" until then. */
  scope?: "account" | "device";
  id: string;
  label: string;
  place_label: string;
  duration_minutes: number;
  distance_km: number;
  road_profile: string;
  character: string;
  maps_url: string;
  created_at: string;
}
