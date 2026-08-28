# Command & Interaction Surface (spec §8)

| Command / interaction | Scope | Effect |
|---|---|---|
| inline `@MemeBot <query>` | any chat | search public + own private, return media results |
| `/find <query>` | DM | same search, richer UI (buttons, "More" pagination) in-chat |
| `/add` (reply to media) | DM | save to **private** pool (quota enforced) |
| `/suggest` (reply to media) | DM | opens **public** submission → review channel vote |
| `/mystatus` | DM | quota usage, trust_score, open submissions, penalties |
| `/report <meme_id>` | DM | reason picker → feeds removal policy |
| `/downvote <meme_id>` | DM | community downvote (§5.5.4) |
| `/appeal <meme_id> <reason>` | DM | appeal a removal |
| `/policy` | DM | current governance policy text |
| `/removals` | DM | public, anonymized removal audit log (§5.7) |
| review-channel 👍/👎 | channel | cast/change vote on an open submission |
| review-channel Keep/Remove | channel | removal-review vote |
| `/admin remove <id> <clause>` | admin DM | manual removal (requires policy clause) |
| `/admin block <hash>` | admin DM | add to illegal-content blocklist (§5.3) |
| `/admin unblock <hash>` | admin DM | remove from blocklist |
| `/admin policy <body>` | admin DM | bump the versioned `/policy` document |

## Flow notes

### `/add` (private pool)
Reply to a photo/GIF/video/voice/audio/sticker → bot asks title → tags
(comma-separated) → NSFW? (Yes/No). On save, quota is checked
(`private_quota`); over-quota offers delete-an-old-one or `/suggest` instead.

### `/suggest` (public pool)
Same capture flow, then the bot creates `Meme(visibility=pending)` +
`Submission(status=open)`, posts to `REVIEW_CHANNEL_ID` with media + 👍/👎
buttons, and notifies the submitter on close. Auto-reject paths (illegal hash,
duplicate) short-circuit before posting.

### Inline & `/find`
Both call `app/search.search`. Inline excludes NSFW from public results by
default. `/find` renders candidates with a "send" button each (logs the
retrieval event + bumps popularity) and a "More" button for pagination.

### Review channel
Votes are weighted per `vote_weight` and upserted (one per user per submission,
changeable until close). A submission closes early once decisive, or when the
window expires.

### Reports / removal
`/report <meme_id>` → reason picker → `file_report` records a `Report` and, if
the same-reason threshold is hit within the window, opens a removal review
(keep/remove) in the channel. `/downvote` feeds the community-downvote path.
