import { useCallback, useEffect, useState } from "react";
import type { Coord } from "../types";

// A saved place the user can drive back to. The shape mirrors the backend
// `saved_places` table (id, label, lat, lng, isDefault) so that moving from
// localStorage to the database later is a change *inside this hook only* — the
// rest of the app asks for places through this interface and never touches the
// store directly. v0.2 surfaces a single Home; the list/default design means
// multiple places is a later UI unlock, not a data migration.
export interface Place {
  id: string;
  label: string;
  lat: number;
  lng: number;
  isDefault: boolean;
}

const KEY = "driftway.places.v1";
const OLD_SETTINGS_KEY = "driftway.settings.v1"; // for one-time Home migration

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

function load(): Place[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    /* fall through to migration / empty */
  }
  // One-time migration: lift an existing Home out of the old settings blob.
  try {
    const oldRaw = localStorage.getItem(OLD_SETTINGS_KEY);
    if (oldRaw) {
      const old = JSON.parse(oldRaw);
      if (old?.home?.lat != null && old?.home?.lng != null) {
        return [
          {
            id: uid(),
            label: "Home",
            lat: old.home.lat,
            lng: old.home.lng,
            isDefault: true,
          },
        ];
      }
    }
  } catch {
    /* ignore */
  }
  return [];
}

export function usePlaces() {
  const [places, setPlaces] = useState<Place[]>(load);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(places));
    } catch {
      /* storage may be unavailable; ignore */
    }
  }, [places]);

  const defaultPlace = places.find((p) => p.isDefault) ?? places[0] ?? null;

  // Save (or update) Home. In v0.2 there is one place; this replaces it.
  const saveHome = useCallback((coord: Coord) => {
    setPlaces((prev) => {
      const existing = prev.find((p) => p.label === "Home");
      if (existing) {
        return prev.map((p) =>
          p.id === existing.id ? { ...p, lat: coord.lat, lng: coord.lng } : p,
        );
      }
      return [
        ...prev.map((p) => ({ ...p, isDefault: false })),
        { id: uid(), label: "Home", lat: coord.lat, lng: coord.lng, isDefault: true },
      ];
    });
  }, []);

  return { places, defaultPlace, saveHome };
}
