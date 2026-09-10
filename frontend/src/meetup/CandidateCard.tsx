import type { VenueCandidate, VoteValue } from "./api";

const VOTE_OPTIONS: { value: VoteValue; label: string }[] = [
  { value: "works", label: "Works for me" },
  { value: "maybe", label: "Could work" },
  { value: "too_far", label: "Too far" },
  { value: "not_this_venue", label: "Not this one" },
];

interface Props {
  candidate: VenueCandidate;
  rank: number;
  names: Map<string, string>;
  onVote: ((candidateId: string, value: VoteValue) => void) | null;
  onRemove: ((id: string) => void) | null;
  /** Only the organiser settles the choice, so only they get this. */
  onSelect?: ((candidateId: string) => void) | null;
}

/**
 * One venue, with every parent's journey shown in minutes.
 *
 * The rule from the brief, and the reason this card looks the way it does:
 * always show absolute minutes per participant, never a fairness percentage
 * alone. "75% similar" makes 90 versus 120 minutes sound like a rounding
 * error, and it is the parent doing the extra half hour who would be misled.
 * The label sits *beside* the numbers, never instead of them.
 */
export function CandidateCard({
  candidate, rank, names, onVote, onRemove, onSelect = null,
}: Props) {
  const anyoneOver = candidate.participant_travel.some((t) => t.exceeds_maximum);
  const mapsUrl =
    `https://www.google.com/maps/dir/?api=1&destination=` +
    `${candidate.coord.lat.toFixed(6)},${candidate.coord.lng.toFixed(6)}&travelmode=driving`;

  return (
    <article className={`mhc${anyoneOver ? " mhc-over" : ""}`}>
      <header className="mhc-head">
        <div className="mhc-title">
          <span className="mhc-rank">{rank}</span>
          <div>
            <h3 className="mhc-name">{candidate.name}</h3>
            {candidate.address_label && (
              <p className="mhc-address">{candidate.address_label}</p>
            )}
          </div>
        </div>
        {candidate.provider_rating != null && (
          <span className="mhc-rating">{candidate.provider_rating.toFixed(1)} ★</span>
        )}
      </header>

      {candidate.participant_travel.length > 0 ? (
        <ul className="mhc-times">
          {candidate.participant_travel.map((t) => (
            <li key={t.participant_id} className="mhc-time">
              <span className="mhc-who">{names.get(t.participant_id) ?? "Someone"}</span>
              <span className={`mhc-min${t.exceeds_maximum ? " mhc-min-over" : ""}`}>
                {Math.round(t.direct_minutes)} min
                {t.exceeds_maximum && (
                  <span className="mhc-over-tag">over their limit</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mhc-pending">
          Travel times not worked out yet — press “Compare travel times”.
        </p>
      )}

      {candidate.participant_travel.length > 1 && (
        <div className="mhc-spread">
          <span>
            Spread: <strong>{Math.round(candidate.fairness_spread_minutes)} min</strong>
          </span>
          <span className="mhc-fit">{candidate.group_fit_label}</span>
        </div>
      )}

      {onVote && (
        <div className="mhc-votes" role="group" aria-label="Your view of this place">
          {VOTE_OPTIONS.map((o) => {
            const chosen = candidate.your_vote === o.value;
            const count = candidate.votes[o.value] ?? 0;
            return (
              <button
                key={o.value}
                className={`mhc-vote${chosen ? " mhc-vote-on" : ""}`}
                aria-pressed={chosen}
                onClick={() => onVote(candidate.id, o.value)}
              >
                {o.label}
                {count > 0 && <span className="mhc-count">{count}</span>}
              </button>
            );
          })}
        </div>
      )}

      <div className="mhc-actions">
        <a
          className="mhc-nav"
          href={mapsUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          Open in Google Maps
        </a>
        <span className="mhc-right">
          {onSelect && (
            <button className="mhc-choose" onClick={() => onSelect(candidate.id)}>
              Choose this
            </button>
          )}
          {onRemove && candidate.added_by_you && (
            <button className="btn-quiet" onClick={() => onRemove(candidate.id)}>
              Remove
            </button>
          )}
        </span>
      </div>
    </article>
  );
}
