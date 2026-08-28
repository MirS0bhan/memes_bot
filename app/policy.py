"""Governance policy engine (spec §5) and versioned policy text (spec §5.7).

Numeric thresholds come from Settings (env-configurable, §7.4) so they can be
tuned without a redeploy. The human-readable policy document is stored in the DB
and seeded here.
"""

from datetime import datetime, timezone

from app.config import get_settings
from app.enums import SubmissionStatus, Visibility

settings = get_settings()

DEFAULT_POLICY_VERSION = "1.0.0"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def vote_weight(user) -> float:
    """Compute a voter's weight from trust_score and account age (spec §5.4).

    - New account (< NEW_ACCOUNT_AGE_DAYS old): reduced weight.
    - Penalized (trust_score below 50): penalized weight.
    - Otherwise: established weight.
    The computation is transparent — surfaced via /mystatus.
    """
    if getattr(user, "is_banned", False):
        return 0.0
    age = _now() - user.created_at
    if user.trust_score < 50:
        return settings.penalized_weight
    if age.days < settings.new_account_age_days:
        return settings.new_account_weight
    return settings.established_weight


def evaluate_submission(net_score: float, up_votes: int, nsfw: bool) -> SubmissionStatus | None:
    """Return the resolved status if decisive, else None (still OPEN).

    Implements spec §5.2.
    """
    approve_threshold = (
        settings.nsfw_approve_net_score if nsfw else settings.approve_net_score
    )
    if net_score >= approve_threshold and up_votes >= settings.approve_min_upvotes:
        return SubmissionStatus.APPROVED
    if net_score <= settings.reject_net_score:
        return SubmissionStatus.REJECTED
    return None


def default_policy_text() -> str:
    s = settings
    return f"""# MemeBot Governance Policy — v{DEFAULT_POLICY_VERSION}

_Last updated: {_now().isoformat()}_

This policy is public and versioned. It governs how memes enter and leave the
**public pool**. The private pool is personal and not subject to voting.

## 1. Who can vote (§5.1)
Any non-banned user may vote. Votes from accounts younger than
{s.new_account_age_days} day(s) count at reduced weight. Voting is rate-limited
to prevent brigading.

## 2. Addition threshold — approval (§5.2)
A *pending* meme is **approved** if, within the {s.vote_window_hours}h voting
window (or immediately once reached):

- `net_score = Σ(up·weight) − Σ(down·weight) ≥ {s.approve_net_score}` **and**
  `up_votes ≥ {s.approve_min_upvotes}`.

NSFW-flagged submissions require a higher bar: `net_score ≥ {s.nsfw_approve_net_score}`.
Approved NSFW memes are **excluded from default search results**.

A pending meme is **rejected** if `net_score ≤ {s.reject_net_score}`, or if the
window closes without reaching the approval threshold. Rejected memes may be
re-submitted once after a {s.resubmit_cooldown_days}-day cool-down.

Nothing reaches the public pool except through this vote. Admins may fast-track
*removal*, never *addition*.

## 3. Auto-reject (§5.3)
- A match against the maintained illegal-content hash list → auto-reject, never
  posted to the channel, auto-reported to admins.
- A duplicate `file_hash` of an already-public meme → merged (no duplicate entry),
  submitter notified.

## 4. Removal policy (§5.5)
A public meme is removed under exactly one documented trigger, each producing a
RemovalCase:

1. **Report threshold**: ≥ {s.report_threshold} distinct reports for the *same*
   reason within {s.report_window_hours}h → auto-suspended, then a mandatory
   keep/remove review vote (same weighting as §2) decided within
   {s.review_vote_window_hours}h.
2. **Legal / DMCA / illegal content**: immediate removal on verified request,
   bypasses voting, `trigger=legal_request`, always logged.
3. **Admin manual removal**: requires a written `policy_clause` reference.
4. **Community downvote after the fact**: decay-weighted organic downvotes past
   threshold → same review-vote process as #1.

Removed media is hidden from all search/suggest surfaces and kept for audit/appeal
(unless illegal content, which is purged).

## 5. Appeals (§5.6)
The submitter (or owner) has {s.appeal_window_days} days after a `removed` decision
to `/appeal`. Appeals go to an admin-only review with a documented outcome.

## 6. Transparency (§5.7)
- `/policy` serves this document.
- `/mystatus` shows your trust_score, weights, and any penalties applied to you.
- A public, anonymized RemovalCase log (meme title + reason + clause, no reporter
  identities) is available.

## 7. Trust & weighting (§5.4)
- New account weight: {s.new_account_weight}
- Established weight: {s.established_weight}
- Penalized weight: {s.penalized_weight} (transparent and reversible)

No silent, permanent shadow-penalties.
"""
