// Mirrors the backend data contracts in core/models.py.
// Keep these in sync if the backend models change.

export type RoadProfile = "motorway" | "mixed" | "quiet";
export type Direction = "surprise" | "N" | "E" | "S" | "W";

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
}

export interface RoadMix {
  motorway: number;
  primary: number;
  secondary: number;
  residential: number;
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
  maps_url: string;
  confidence: "low" | "medium" | "high";
}

export interface GenerateResponse {
  routes: RouteOption[];
  target_minutes: number;
  tolerance_minutes: number;
  generated_at: string;
  provider: string;
  candidates_evaluated: number;
}

export interface FeedbackRequest {
  route_id: string;
  predicted_minutes: number;
  actual_minutes?: number | null;
  would_use_again?: boolean | null;
  baby_slept?: "yes" | "no" | "unknown" | null;
  notes?: string | null;
}
