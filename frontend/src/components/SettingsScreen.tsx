import type { RoadProfile } from "../types";
import type { Settings, Units } from "../hooks/useSettings";
import { ChipGroup } from "./ChipGroup";

interface Props {
  settings: Settings;
  update: (patch: Partial<Settings>) => void;
}

const PROFILE_OPTS: { value: RoadProfile; label: string }[] = [
  { value: "motorway", label: "Motorways" },
  { value: "mixed", label: "Mixed" },
  { value: "quiet", label: "Quieter" },
];

// Settings + a short About/roadmap section. Kept on one screen so it's easy to
// reach and not over-built. Light/dark theme is deliberately deferred to a
// later version (the app is designed for the night-drive dark mood).
export function SettingsScreen({ settings, update }: Props) {
  return (
    <main className="settings">
      <h2 className="settings-title">Settings</h2>

      <ChipGroup
        legend="Distance units"
        columns={2}
        options={[
          { value: "km" as Units, label: "Kilometres" },
          { value: "mi" as Units, label: "Miles" },
        ]}
        value={settings.units}
        onChange={(v) => update({ units: v })}
      />

      <ChipGroup
        legend="Quick drive home — road style"
        columns={3}
        options={PROFILE_OPTS}
        value={settings.quickDriveProfile}
        onChange={(v) => update({ quickDriveProfile: v })}
      />
      <p className="settings-note">
        Quieter roads are usually smoothest for a sleeping baby. Avoiding speed
        bumps and traffic lights directly is coming in a later version.
      </p>

      <div className="settings-about">
        <h3 className="settings-about-title">About Driftway</h3>
        <p>
          Driftway makes circular drives of a length you choose and brings you
          home — for when a little one sleeps best on the move. Pick a duration
          and road style, get three loops, and start one in Google Maps.
        </p>
        <p className="settings-safety">
          Car seats are designed for safe travel rather than routine sleep. On
          longer journeys, take regular breaks, follow your child-seat
          manufacturer's instructions, and take extra care with very young or
          premature babies. This doesn't replace advice from a healthcare
          professional.
        </p>

        <h3 className="settings-about-title">What's coming</h3>
        <ul className="settings-roadmap">
          <li>Smoother routing that avoids speed bumps and traffic lights</li>
          <li>More saved places, not just Home</li>
          <li>"A bit more" extensions while you're out</li>
          <li>Native apps and in-car (Android Auto, CarPlay)</li>
        </ul>

        <p className="settings-feedback">
          Got a thought after a drive? The quick "would use again?" prompt after
          each route is the most useful thing you can send — it's how the routes
          get better.
        </p>
      </div>
    </main>
  );
}
