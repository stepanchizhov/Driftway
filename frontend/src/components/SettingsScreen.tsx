import { useRef, useState } from "react";
import type { RoadProfile } from "../types";
import { APP_VERSION, BUILD, RELEASES } from "../version";
import type { Settings, Units } from "../hooks/useSettings";
import { ChipGroup } from "./ChipGroup";
import { AccountSection } from "../auth/AccountSection";

interface Props {
  settings: Settings;
  update: (patch: Partial<Settings>) => void;
  /** The server's release and build, once it has answered. */
  server: { version: string; build: string } | null;
}

const PROFILE_OPTS: { value: RoadProfile; label: string }[] = [
  { value: "motorway", label: "Motorways" },
  { value: "mixed", label: "Mixed" },
  { value: "quiet", label: "Quieter" },
];

// Settings + a short About/roadmap section. Kept on one screen so it's easy to
// reach and not over-built. Light/dark theme is deliberately deferred to a
// later version (the app is designed for the night-drive dark mood).
const NAV_APPS = [
  { id: "google_maps", label: "Google Maps" },
  { id: "waze", label: "Waze" },
  { id: "apple_maps", label: "Apple Maps" },
];

export function SettingsScreen({ settings, update, server }: Props) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const history = useRef<HTMLDetailsElement | null>(null);
  // Builds are compared, not versions: two builds of one release differ too.
  // A frontend and API deploy separately on Render, so for a few minutes after
  // a push they can legitimately differ.
  const mismatch =
    server !== null && BUILD !== "dev" && server.build !== "dev" && server.build !== BUILD;

  return (
    <main className="settings">
      <h2 className="settings-title">Settings</h2>
      <p className="settings-version">
        Driftway {APP_VERSION} · build <span className="mono">{BUILD}</span> ·{" "}
        <a
          href="#whats-new"
          onClick={(e) => {
            e.preventDefault();
            setHistoryOpen(true);
            // After the details element has opened.
            window.setTimeout(() => history.current?.scrollIntoView({ behavior: "smooth" }), 0);
          }}
        >
          What&rsquo;s new?
        </a>
      </p>

      {/* First, because it is the only block here that is about the person
          rather than the drive - and because the data controls inside it are
          the ones someone arrives looking for. Renders nothing when no
          sign-in provider is configured. */}
      <AccountSection />

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
          Driftway is for when a little one sleeps best on the move: drives of
          the length you choose that bring you home, walks checked against your
          pram or carrier, and a fair place to meet another parent. Each one
          says what&rsquo;s known about it and what isn&rsquo;t.
        </p>
        <p className="settings-safety">
          Car seats are designed for safe travel rather than routine sleep. On
          longer journeys, take regular breaks, follow your child-seat
          manufacturer's instructions, and take extra care with very young or
          premature babies. For slings and carriers, follow the TICKS guidance
          in the Walk tab. This doesn't replace advice from a healthcare
          professional.
        </p>

        <h3 className="settings-about-title">Version</h3>
        <dl className="settings-builds">
          <div>
            <dt>App</dt>
            <dd>
              {APP_VERSION} · build <span className="mono">{BUILD}</span>
            </dd>
          </div>
          <div>
            <dt>Server</dt>
            <dd>
              {server ? (
                <>
                  {server.version} · build <span className="mono">{server.build}</span>
                </>
              ) : (
                "not reached yet"
              )}
            </dd>
          </div>
        </dl>
        {mismatch && (
          <p className="settings-note" role="status">
            The app and the server are from different builds. Just after an
            update one may still be deploying; if it lasts, close Driftway
            completely and open it again to load the newest app.
          </p>
        )}

        <details
          id="whats-new"
          ref={history}
          className="settings-whatsnew"
          open={historyOpen}
          onToggle={(e) => setHistoryOpen(e.currentTarget.open)}
        >
          <summary>What&rsquo;s new?</summary>
          {RELEASES.map((r) => (
            <section key={r.version} className="release">
              <h4>
                {r.version} <span className="release-date">{r.date}</span>
              </h4>
              <ul>
                {r.changes.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </section>
          ))}
          <p className="settings-note">
            Versions before 0.7.0 weren&rsquo;t shown in the app at the time;
            they were numbered afterwards from the project history.
          </p>
        </details>

        <p className="settings-links">
          <a href="/beta.html" target="_blank" rel="noopener noreferrer">
            Guide for testers
          </a>{" "}
          ·{" "}
          <a href="/privacy.html" target="_blank" rel="noopener noreferrer">
            Privacy policy
          </a>{" "}
          ·{" "}
          <a href="/delete-account.html" target="_blank" rel="noopener noreferrer">
            Deleting your account
          </a>
        </p>

        <h3 className="settings-about-title">What's coming</h3>
        <p className="settings-note">
          What we&rsquo;re working towards. These aren&rsquo;t promises, and the
          order may change.
        </p>
        <ul className="settings-roadmap">
          <li>Driftway as an app from Google Play, for beta testers first</li>
          <li>Calmer drives that steer away from mapped speed bumps</li>
          <li>Drives that turn around less often</li>
          <li>More saved places, not just Home</li>
          <li>Your own walking pace, for walk times</li>
          <li>Walks by rivers and canals</li>
          <li>Later: in the car (Android Auto), and iPhone</li>
        </ul>

        <p className="settings-feedback">
          Got a thought after a drive? The quick "would use again?" prompt after
          each route is the most useful thing you can send — it's how the routes
          get better.
        </p>
      </div>

      <section className="set-block">
        <span className="set-legend">Navigation app</span>
        <div className="set-row">
          {NAV_APPS.map((app) => (
            <button
              key={app.id}
              className={`set-opt${
                settings.preferredNavigation === app.id ? " set-opt-on" : ""
              }`}
              aria-pressed={settings.preferredNavigation === app.id}
              onClick={() => update({ preferredNavigation: app.id })}
            >
              {app.label}
            </button>
          ))}
        </div>
        <p className="set-hint">
          Used when it can follow the whole route. Shaped nap routes need
          waypoints, which only Google Maps accepts from a link — we&rsquo;ll
          say so rather than quietly drive you somewhere shorter.
        </p>
      </section>
    </main>
  );
}
