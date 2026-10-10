import { useEffect, useRef, useState } from "react";
import { sendAppFeedback, type FeedbackContext } from "../api";
import { APP_VERSION, BUILD } from "../version";

/**
 * Feedback about the app, from any tab - 0.8, for the beta.
 *
 * Opened from the header, so a tester can report wherever they are. It knows
 * which tab they were on and which version and build they are using, and
 * sends both with the message, so a report can be matched to the code that
 * produced it. Unlike the "would use again?" prompt after a drive, failures
 * are shown: a beta tester needs to know whether the report arrived.
 */

const CONTEXT_LABEL: Record<FeedbackContext, string> = {
  stillasleep: "Still asleep",
  plan: "Plan a drive",
  meetup: "Meet up",
  walk: "Walk",
  settings: "Settings",
};

export function AppFeedback({
  context,
  owner,
  onClose,
}: {
  context: FeedbackContext;
  owner?: string;
  onClose: () => void;
}) {
  const [message, setMessage] = useState("");
  const [state, setState] = useState<"editing" | "sending" | "sent" | "failed">("editing");
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    box.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function send() {
    setState("sending");
    setError(null);
    try {
      await sendAppFeedback({
        context,
        message: message.trim(),
        app_version: APP_VERSION,
        build: BUILD,
        owner,
      });
      setState("sent");
    } catch (e) {
      setState("failed");
      setError(e instanceof Error ? e.message : "Couldn't send it just now.");
    }
  }

  return (
    <div className="appfb-backdrop" role="presentation" onClick={onClose}>
      <div
        className="appfb"
        role="dialog"
        aria-modal="true"
        aria-labelledby="appfb-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="appfb-title" className="appfb-title">
          Feedback
        </h2>
        {state === "sent" ? (
          <>
            <p>Thank you — it&rsquo;s arrived. That&rsquo;s how Driftway gets better.</p>
            <button className="btn-primary" onClick={onClose}>
              Done
            </button>
          </>
        ) : (
          <>
            <p className="appfb-sub">
              About: {CONTEXT_LABEL[context]} · Driftway {APP_VERSION} (build {BUILD})
            </p>
            <label className="account-field">
              <span>What worked, what didn&rsquo;t, what you expected</span>
              <textarea
                id="appfb-message"
                ref={box}
                rows={6}
                maxLength={2000}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
              />
            </label>
            <p className="walks-hint">
              Please don&rsquo;t include your address or other people&rsquo;s
              details. If you&rsquo;re signed in, this is kept with your account
              and deleted with it.
            </p>
            {error && <p className="account-error">{error}</p>}
            <div className="appfb-actions">
              <button
                className="btn-primary"
                disabled={!message.trim() || state === "sending"}
                onClick={() => void send()}
              >
                {state === "sending" ? "Sending…" : "Send"}
              </button>
              <button className="btn-quiet" onClick={onClose}>
                Cancel
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
