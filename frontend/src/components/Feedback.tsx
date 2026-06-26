import { useState } from "react";
import type { RouteOption } from "../types";
import { sendFeedback } from "../api";

interface Props {
  route: RouteOption;
  owner?: string;
  onDone: () => void;
}

// Two-tap "would use again?" plus an optional actual-duration field, matching
// the Alpha 0 scope. Records predicted-vs-actual, the core learning signal.
export function Feedback({ route, owner, onDone }: Props) {
  const [actual, setActual] = useState("");
  const [sent, setSent] = useState(false);

  function submit(wouldUseAgain: boolean) {
    sendFeedback({
      route_id: route.id,
      predicted_minutes: route.predicted_minutes,
      actual_minutes: actual ? Number(actual) : null,
      would_use_again: wouldUseAgain,
      owner,
    });
    setSent(true);
  }

  if (sent) {
    return (
      <div className="feedback feedback-done">
        <p>Logged — thanks. That's how the routes get better.</p>
        <button className="btn-quiet" onClick={onDone}>
          Done
        </button>
      </div>
    );
  }

  return (
    <div className="feedback">
      <p className="feedback-q">How did that route go?</p>

      <label className="feedback-actual">
        Actual time, if you noticed
        <span className="feedback-actual-row">
          <input
            inputMode="numeric"
            pattern="[0-9]*"
            placeholder={String(Math.round(route.predicted_minutes))}
            value={actual}
            onChange={(e) => setActual(e.target.value.replace(/[^0-9]/g, ""))}
          />
          <span>min</span>
        </span>
      </label>

      <div className="feedback-buttons">
        <button className="btn-no" onClick={() => submit(false)}>
          Wouldn't use again
        </button>
        <button className="btn-yes" onClick={() => submit(true)}>
          Would use again
        </button>
      </div>

      <button className="btn-skip" onClick={onDone}>
        Skip
      </button>
    </div>
  );
}
