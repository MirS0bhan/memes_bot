# Governance & Moderation Policy (spec §5)

This is the explicit, published part of the bot. All numeric thresholds are
env-configurable (see `deployment.md`) so they can be tuned without a redeploy.

## Who can vote (§5.1)
Any non-banned user may vote. Votes from accounts younger than
`NEW_ACCOUNT_AGE_DAYS` count at reduced weight. Voting is rate-limited.

## Addition threshold — approval (§5.2)
A `pending` meme is **approved** if, within the `VOTE_WINDOW_HOURS` window (or
immediately once reached):

- `net_score = Σ(up·weight) − Σ(down·weight) ≥ APPROVE_NET_SCORE`
- **and** `up_votes ≥ APPROVE_MIN_UPVOTES`.

NSFW-flagged submissions require `net_score ≥ NSFW_APPROVE_NET_SCORE` (higher
bar) and are excluded from default search results even once approved.

A pending meme is **rejected** if `net_score ≤ REJECT_NET_SCORE`, or if the
window closes without reaching the approval threshold. Rejected memes may be
re-submitted once after `RESUBMIT_COOLDOWN_DAYS`.

Nothing reaches the public pool except through this vote.

The evaluation lives in `app/policy.py:evaluate_submission` and is unit-tested.

## Auto-reject (§5.3)
- **Illegal-content hash match**: if a submitted meme's `file_hash` is in
  `illegal_hashes`, it is auto-rejected *before* being stored or posted to the
  channel, admins are notified, and a `RemovalCase(trigger=legal_request)` is
  written. The durable copy (if any) is purged.
- **Duplicate**: a `file_hash` already in the public pool → no duplicate entry;
  the submitter is told it's already public.

## Vote weighting (§5.4)
`app/policy.py:vote_weight(user)`:
- New account (`< NEW_ACCOUNT_AGE_DAYS`): `NEW_ACCOUNT_WEIGHT` (0.5)
- Established: `ESTABLISHED_WEIGHT` (1.0)
- Penalized (`trust_score < 50`): `PENALIZED_WEIGHT` (0.25)

Penalties are transparent and visible via `/mystatus`. No silent permanent
shadow-penalties.

## Removal policy (§5.5)
A public meme is removed under exactly one documented trigger, each producing a
`RemovalCase`:

1. **Report threshold**: `≥ REPORT_THRESHOLD` distinct reports for the *same*
   reason within `REPORT_WINDOW_HOURS` → auto-suspended, then a mandatory
   keep/remove review vote (channel) decided within `REVIEW_VOTE_WINDOW_HOURS`.
2. **Legal / DMCA / illegal** (`/admin remove` with clause `legal_request`, or
   `legal_remove`): immediate, bypasses voting, always logged.
3. **Admin manual** (`/admin remove <id> <clause>`): requires a written clause.
4. **Community downvote after the fact** (`/downvote`): once
   `downvotes ≥ COMMUNITY_DOWNVOTE_THRESHOLD`, same review-vote process as #1
   (trigger `community_downvote`).

Removed media is hidden and kept for audit/appeal (illegal content purged).

## Appeals (§5.6)
`/appeal <meme_id> <reason>` within `APPEAL_WINDOW_DAYS` after a `removed`
decision opens an admin-only review (`RemovalCase.decision = appeal_pending`).

## Transparency surfaces (§5.7)
- `/policy` — current versioned policy text (from `policy_documents`).
- `/mystatus` — quota, `trust_score`, effective vote weight, open submissions,
  ban state.
- `/removals` — public, anonymized `RemovalCase` log (title + clause + decision,
  no reporter identities).
- `/admin policy <body>` — admins bump the policy version.

## Illegal-content blocklist management
- Seed via `ILLEGAL_HASHES` env (comma-separated sha256), applied by the
  migration.
- Runtime: `/admin block <hash>` / `/admin unblock <hash>`.
