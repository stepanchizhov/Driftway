# Identity, invitations and sessions

**Phase A, 14 September 2026.** What exists, what it guarantees, and the one
thing still missing before real beta invitations can go out.

---

## The gate, stated plainly

**The framework gate has NOT passed.** Everything below works and is tested,
but there is **no managed identity provider configured**. The session mechanism
in the repository is explicitly staging-only: it proves the invite flow end to
end, and it is the first thing to delete once a provider is chosen.

Nothing here should be read as a production authentication integration. Mocked
and local tests do not prove one.

---

## Ownership map

| Module | Owns | Must never hold |
|---|---|---|
| `core/accounts.py` | account ids, verified identity mapping, sessions, account status, invites | coordinates, travel history, child details |
| `core/meetups.py` | participants, private origins, votes, results | login email, account credentials |
| `hooks/usePlaces.ts` (device) | saved places | anything server-side today |

An account is an identity and entitlement anchor. It is not a location dossier.
`UserAccount` has no coordinate column and must not gain one: if account-linked
saved places are added later, they belong in their own table with independent
deletion.

**Registration policy, authentication and entitlements are separate.** Account
creation being closed does not gate stateless planning — Loop, Destination,
Still Asleep and search all work with no account at all, and a guest can join a
meetup while registration is closed. There is no global login wall and adding
one would break the product's core promise.

---

## Capabilities

Four, none interchangeable, each tested against the others:

| Capability | Grants | Does not grant |
|---|---|---|
| Beta invite | one account activation | reading any meetup |
| Participant join token | one participant's writes in one meetup | organiser actions, other meetups |
| Organiser token | venue selection in their meetup | anything in another meetup |
| Results slug | read-only redacted view | any write at all |

A signed-in account still needs the relevant capability. Being authenticated is
not authorisation.

---

## Invitations

- **High entropy**, hashed at rest. The raw token is returned exactly once, at
  creation, and never appears in a listing.
- **In the request body, not the query string.** A token in a URL is a token in
  the access log and in any `Referer` the page emits.
- **POST only**, so a link preview or unauthenticated GET cannot consume one.
- **Expiry and revocation** enforced server-side.

### Redemption is exactly once

Redemption claims the invite with a conditional write:

```sql
UPDATE beta_access_invites
   SET accepted_at = ?, accepted_by_user_id = ?
 WHERE id = ? AND accepted_at IS NULL AND revoked_at IS NULL
```

and checks the affected row count. A status check alone was not enough: two
concurrent requests can both read an invite as unused before either commits,
which produced two accounts from one invitation. The database now decides, and
the loser rolls back so no stranded account remains.

Covered by `test_concurrent_redemption_yields_exactly_one_account`, which runs
two real redemptions against a barrier.

### An existing tester clicking a second link

An invite **bound to an address** that already has an active account returns
that account rather than creating a duplicate, and grants nothing extra. The
binding is set by the founder at mint time, which is why it is trustworthy
enough to match on.

A **client-supplied email is never** used for this lookup. Matching on a
self-declared address would let anyone claim another person's account by typing
their email.

---

## Sessions

Staging-only, HttpOnly, `SameSite=Lax`, `Secure` when the request is HTTPS.

- Authorisation is re-checked per request, not baked into the cookie. **A
  disabled account stops authenticating immediately**, not when its cookie
  expires.
- Sign-out deletes the server-side session row, so the cookie is dead even if
  copied beforehand.
- Expired sessions do not authenticate.

`SameSite=Lax` blocks cross-site POST cookies, which covers the obvious CSRF
shape for these endpoints. **A real provider integration should revisit this
properly** rather than inherit the assumption.

### Disabling and deletion

`POST /api/admin/accounts/{id}/disable` (admin token) disables an account and
drops its sessions. It deliberately **does not delete their meetup
participation** — removing that would silently rewrite other people's plans.

Deletion and anonymisation are a separate, deliberate operation and are **not
built**. Before real users, decide: what is erased, what is anonymised in place,
and how long identity is retained. Stating no policy is itself a policy, and the
wrong one.

---

## Choosing a managed provider

**Not selected. This is the remaining Phase A dependency and it needs an owner
decision plus external provisioning.**

The seam exists: `UserAccount.auth_provider` and `auth_subject`, both nullable,
with a unique verified identity intended to map to `auth_subject`. Adopting a
provider means validating its token server-side — issuer, audience, expiry,
signature — then finding or creating the account for that subject.

Non-negotiable when it happens:

- **No home-grown passwords**, and no mock authentication in production.
- **Never trust a client-supplied email, user id or entitlement.** Verify the
  provider's token server-side.
- **Do not auto-link by unverified email.**
- Secrets stay server-side; raw tokens stay out of logs and analytics.

Verify current pricing, quotas and terms from official documentation at the
time of the decision — this document does not select a vendor, and figures go
stale.

---

## Storage and schema

Account and invite state **requires durable storage before real invitations**.
An ephemeral SQLite fallback keeps routing alive during an outage; it is not
evidence of durable identity. Check the deployed `DATABASE_URL` before sending
anything to a tester.

### Migrations

`create_all()` adds missing **tables** but never missing **columns**. That
caused a production incident. `core/migrations.py` now runs ordered,
forward-only steps at startup:

- **Additive only** — no step drops a column or table. Rollback is "deploy the
  previous code", which still reads the older columns.
- **Idempotent** — every step checks the schema first, so restarts are safe.
- **Recorded** in `schema_migrations`.
- **Never fatal** — a failing step logs loudly and leaves routing and search
  serving, exactly as an unreachable database does.

`/api/health` reports `schema_pending`. **Non-empty means some feature will fail
even though storage answers.**

Alembic remains the right destination. This is a stepping stone that is honest
about being one.

> **Superseded advice.** Earlier deployment notes said a staging schema change
> means dropping the meetup tables and letting them rebuild. **Do not do that
> once real testers exist** — it destroys their accounts and invitations. Add a
> migration step instead.

---

## Failure isolation

| Failure | Routing / search | Account, admin, meetup |
|---|---|---|
| Database unreachable | keep working | scoped 503 |
| Schema step outstanding | keep working | affected feature fails; visible on health |
| Auth provider unavailable | keep working | protected operations denied |

Protected operations **fail closed**. Resilience never means bypassing a
permission check. Degraded features are never reported as healthy.

---

## Founder test procedure

No messages are sent to anyone by following this.

1. Confirm `DATABASE_URL` points at durable Postgres and `/api/health` shows
   `"storage":"ok"` with `"schema_pending":[]`.
2. Mint an invite:
   ```bash
   curl -X POST "$API/api/admin/beta-invites?ttl_days=14&bound_email=you@example.com" \
     -H "X-Admin-Token: $ADMIN_API_TOKEN"
   ```
   The raw token is in that response only.
3. Redeem it:
   ```bash
   curl -X POST "$API/api/auth/accept-beta-invite" \
     -H "Content-Type: application/json" \
     -d '{"invite_token":"<raw>","display_name":"Stepan"}' -c cookies.txt
   ```
4. `curl "$API/api/auth/me" -b cookies.txt` → your account, **no email field**.
5. Redeem the same token again → refused as already used.
6. Disable, then re-check `/auth/me` → null:
   ```bash
   curl -X POST "$API/api/admin/accounts/<id>/disable" -H "X-Admin-Token: $ADMIN_API_TOKEN"
   ```
7. In a fresh private window, open a meetup participant link and confirm you can
   join, vote and view results **with no account**.

If step 1 fails, stop: everything after it is theatre on disposable storage.

---

## Environment variables

Names only.

| Name | Purpose |
|---|---|
| `DATABASE_URL` | durable storage. Absent ⇒ ephemeral SQLite, unsuitable for real accounts |
| `REGISTRATION_MODE` | `closed` / `invite_only` / `open`. Unreadable values fall back to `invite_only`, never open |
| `ADMIN_API_TOKEN` | admin operations. Unset ⇒ every admin endpoint refuses |
| `MEET_HALFWAY_ENABLED` | the meetup surface |
| `ROUTING_PROVIDER`, `TOMTOM_API_KEY`, `ALLOWED_ORIGINS` | unchanged |
