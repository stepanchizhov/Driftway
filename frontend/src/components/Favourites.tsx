import { useEffect, useState } from "react";
import type { Favourite } from "../types";
import type { Units } from "../hooks/useSettings";
import { formatDistance } from "../lib/units";
import { listFavourites, deleteFavourite } from "../api";

interface Props {
  owner: string;
  onBack: () => void;
  units?: Units;
}

const PROFILE_LABEL: Record<string, string> = {
  motorway: "Motorways",
  mixed: "Mixed",
  quiet: "Quieter roads",
};

// A dedicated screen for saved drives. Each opens in Google Maps (which
// recomputes live traffic), or can be removed.
export function Favourites({ owner, units = "km" }: Props) {
  const [items, setItems] = useState<Favourite[] | null>(null);

  useEffect(() => {
    let alive = true;
    listFavourites(owner).then((favs) => {
      if (alive) setItems(favs);
    });
    return () => {
      alive = false;
    };
  }, [owner]);

  async function remove(id: string) {
    setItems((prev) => (prev ? prev.filter((f) => f.id !== id) : prev));
    await deleteFavourite(id, owner);
  }

  return (
    <main className="favs">
      <div className="favs-head">
        <h2 className="favs-title">Saved drives</h2>
      </div>

      {items === null && <p className="favs-empty">Loading…</p>}

      {items !== null && items.length === 0 && (
        <p className="favs-empty">
          No saved drives yet. Tap the ☆ on a route to save it here.
        </p>
      )}

      {items?.map((f) => (
        <article key={f.id} className="fav-card">
          <div className="fav-main">
            <div className="fav-figures">
              <span className="fav-min">{f.duration_minutes}</span>
              <span className="fav-min-unit">min</span>
              {f.distance_km > 0 && (
                <span className="fav-dist">{formatDistance(f.distance_km, units)}</span>
              )}
            </div>
            <p className="fav-meta">
              {f.label ? f.label + " · " : ""}
              {PROFILE_LABEL[f.road_profile] ?? f.road_profile}
              {f.place_label ? " · to " + f.place_label : ""}
            </p>
            {f.character && <p className="fav-character">{f.character}</p>}
          </div>
          <div className="fav-actions">
            {f.maps_url && (
              <a
                className="fav-go"
                href={f.maps_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                Start
              </a>
            )}
            <button
              className="fav-del"
              onClick={() => remove(f.id)}
              aria-label="Remove saved drive"
            >
              Remove
            </button>
          </div>
        </article>
      ))}
    </main>
  );
}
