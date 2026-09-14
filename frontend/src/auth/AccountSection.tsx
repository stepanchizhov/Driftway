import { useCallback, useEffect, useState } from "react";

import { authConfigured } from "./config";
import { useDriftwayAuth } from "./AuthProvider";
import {
  AccountError,
  downloadMyData,
  eraseMyAccount,
  fetchAccount,
  fetchRegistrationMode,
  redeemInvite,
  type Account,
  type RegistrationMode,
} from "./api";

/**
 * The account surface: sign in, get admitted, take your data, leave.
 *
 * Self-contained on purpose - it reaches for its own state rather than having
 * it threaded down from App, because nothing else in the app needs to know
 * whether anyone is signed in. Renders nothing at all when no provider is
 * configured, so a deployment without Auth0 looks exactly as it did before.
 *
 * Signing in and having an account are kept visibly separate, because they
 * are separate: Auth0 says who you are, an invitation says you were admitted.
 * Collapsing the two would make "signed in but not invited" look like a bug
 * rather than the expected middle state it is.
 */
export function AccountSection() {
  if (!authConfigured) return null;
  return <AccountPanel />;
}

function AccountPanel() {
  const { isAuthenticated, isLoading, user, signIn, signOut } =
    useDriftwayAuth();

  const [account, setAccount] = useState<Account | null>(null);
  const [checked, setChecked] = useState(false);
  const [mode, setMode] = useState<RegistrationMode>("invite_only");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!isAuthenticated) {
      setAccount(null);
      setChecked(true);
      return;
    }
    try {
      setAccount(await fetchAccount());
    } catch (e) {
      setError(e instanceof AccountError ? e.message : "Something went wrong.");
    } finally {
      setChecked(true);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    void fetchRegistrationMode().then(setMode);
  }, []);

  if (isLoading) {
    return (
      <section className="set-block">
        <span className="set-legend">Account</span>
        <p className="set-hint">Checking…</p>
      </section>
    );
  }

  return (
    <section className="set-block">
      <span className="set-legend">Account</span>

      {error && <p className="account-error">{error}</p>}

      {!isAuthenticated && (
        <>
          <p className="set-hint">
            You don&rsquo;t need an account to plan a drive. Signing in is for
            meeting other parents halfway, so your saved places and meetups
            follow you between devices.
          </p>
          <button className="btn-primary" onClick={() => void signIn()}>
            Sign in
          </button>
        </>
      )}

      {isAuthenticated && checked && !account && (
        <Admission mode={mode} onJoined={setAccount} onSignOut={signOut} />
      )}

      {isAuthenticated && account && (
        <SignedIn
          account={account}
          email={user?.email}
          onSignOut={signOut}
          onErased={() => {
            setAccount(null);
            void signOut();
          }}
        />
      )}
    </section>
  );
}

/**
 * Signed in to Auth0, but not yet admitted to Driftway.
 *
 * Which of the three doors this shows is decided by the server's reported
 * registration mode, not by a hardcoded assumption - so the day the alpha
 * opens up, the invitation box stops being asked for without a rebuild.
 */
function Admission({
  mode,
  onJoined,
  onSignOut,
}: {
  mode: RegistrationMode;
  onJoined: (a: Account) => void;
  onSignOut: () => void;
}) {
  const [token, setToken] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (mode === "closed") {
    return (
      <>
        <p className="set-hint">
          Driftway isn&rsquo;t taking new accounts at the moment. Route planning
          still works without one.
        </p>
        <button className="btn-quiet" onClick={onSignOut}>
          Sign out
        </button>
      </>
    );
  }

  const needsInvite = mode === "invite_only";

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      onJoined(await redeemInvite({ inviteToken: token, displayName: name }));
    } catch (e) {
      setError(e instanceof AccountError ? e.message : "That didn't work.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="set-hint">
        {needsInvite
          ? "Driftway is in a closed test. Paste the invitation you were sent to finish setting up your account."
          : "Almost there — pick a name other parents will see."}
      </p>

      <label className="account-field">
        <span>Your name</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="What other parents see"
          autoComplete="nickname"
        />
      </label>

      {needsInvite && (
        <label className="account-field">
          <span>Invitation</span>
          <input
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Paste your invitation"
            autoComplete="off"
            spellCheck={false}
          />
        </label>
      )}

      {error && <p className="account-error">{error}</p>}

      <button
        className="btn-primary"
        disabled={busy || (needsInvite && token.trim().length < 8)}
        onClick={() => void submit()}
      >
        {busy ? "Checking…" : needsInvite ? "Join Driftway" : "Create account"}
      </button>
      <button className="btn-quiet" onClick={onSignOut}>
        Sign out
      </button>
    </>
  );
}

function SignedIn({
  account,
  email,
  onSignOut,
  onErased,
}: {
  account: Account;
  email?: string;
  onSignOut: () => void;
  onErased: () => void;
}) {
  const [busy, setBusy] = useState<null | "export" | "erase">(null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(what: "export" | "erase") {
    setBusy(what);
    setError(null);
    try {
      if (what === "export") await downloadMyData();
      else {
        await eraseMyAccount();
        onErased();
      }
    } catch (e) {
      setError(e instanceof AccountError ? e.message : "Something went wrong.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <p className="account-who">
        Signed in{account.display_name ? ` as ${account.display_name}` : ""}
        {email ? ` (${email})` : ""}.
      </p>

      <button
        className="btn-quiet"
        disabled={busy !== null}
        onClick={() => void run("export")}
      >
        {busy === "export" ? "Preparing…" : "Download my data"}
      </button>
      <p className="set-hint">
        Everything Driftway holds about you, including your exact starting
        points. Other parents&rsquo; starting points aren&rsquo;t included —
        those aren&rsquo;t yours to receive.
      </p>

      <button className="btn-quiet" onClick={onSignOut} disabled={busy !== null}>
        Sign out
      </button>

      {!confirming ? (
        <button
          className="btn-danger"
          disabled={busy !== null}
          onClick={() => setConfirming(true)}
        >
          Delete my account
        </button>
      ) : (
        <div className="account-confirm">
          <p>
            This deletes your account, your saved places, your votes, and any
            meetup you organised — for everyone in it. It can&rsquo;t be undone.
          </p>
          <p className="set-hint">
            If you want a copy first, download your data before deleting.
          </p>
          <button
            className="btn-danger"
            disabled={busy !== null}
            onClick={() => void run("erase")}
          >
            {busy === "erase" ? "Deleting…" : "Yes, delete everything"}
          </button>
          <button
            className="btn-quiet"
            disabled={busy !== null}
            onClick={() => setConfirming(false)}
          >
            Keep my account
          </button>
        </div>
      )}

      {error && <p className="account-error">{error}</p>}
    </>
  );
}
