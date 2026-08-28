# Data Model (spec §2, §4)

Defined in `app/models.py` (SQLAlchemy, Postgres). All timestamps are
`timestamptz` (UTC).

## Entities

### User
| field | type | notes |
|---|---|---|
| id | bigint (PK) | internal id |
| telegram_id | bigint, unique | Telegram user id |
| username | text, nullable | cached, best-effort |
| locale | text | user's UI language (`en`/`fa`); set via `/language`, used by `app/i18n.py` |
| private_quota | int | default `DEFAULT_PRIVATE_QUOTA` (200) |
| trust_score | int | affects vote weight (§5.4) |
| is_banned | bool | |
| created_at | timestamptz | |

### Meme
| field | type | notes |
|---|---|---|
| id | uuid (PK) | |
| owner_id | bigint, FK→User, nullable | null if owner deleted (meme survives) |
| visibility | enum | `private`, `pending`, `public`, `rejected`, `removed` |
| media_type | enum | `photo`, `video`, `animation`, `voice`, `audio`, `sticker` |
| telegram_file_id | text | **primary** retrieval handle |
| storage_object_key | text, nullable | durable fallback in object storage |
| file_hash | text (sha256), indexed | de-duplication |
| title | text | short label |
| description | text, nullable | |
| tags | text[] | normalized lowercase, GIN-indexed |
| language | text | |
| nsfw | bool | visibility rules |
| downvotes | int | community-downvote counter (§5.5.4) |
| submitted_at | timestamptz | |
| reviewed_at | timestamptz, nullable | |
| source_chat_id | bigint, nullable | abuse tracing |
| search_tsv | tsvector (generated) | full-text index source (§6.1) |
| popularity | float | retrieval/popularity signal |

Indexes: GIN on `tags`, GIN on `search_tsv`, btree on `file_hash`, btree on
`visibility`.

### Submission (public-pool proposal)
| field | type |
|---|---|
| id | uuid |
| meme_id | FK→Meme (unique) |
| submitter_id | FK→User |
| channel_message_id | bigint — vote post in review channel |
| status | `open`, `approved`, `rejected`, `expired` |
| opened_at / closed_at | timestamptz |

### Vote
| field | type |
|---|---|
| id | bigint |
| submission_id | FK→Submission |
| voter_id | FK→User |
| value | `up`, `down` |
| weight | numeric — derived from voter trust at cast time |
| created_at | timestamptz |

Unique `(submission_id, voter_id)` — one changeable vote per user per submission.

### Report
| field | type |
|---|---|
| id | bigint |
| meme_id | FK→Meme |
| reporter_id | FK→User |
| reason | `nsfw_unflagged`, `hate_harassment`, `copyright`, `spam_low_quality`, `illegal`, `other` |
| note | text, nullable |
| created_at | timestamptz |

### RemovalCase (audit trail — every removal writes one)
| field | type |
|---|---|
| id | uuid |
| meme_id | FK→Meme |
| trigger | `report_threshold`, `admin_manual`, `legal_request`, `community_downvote` |
| policy_clause | text — which rule fired |
| decided_by | FK→User, nullable (null if automatic) |
| decision | `removed`, `kept`, `appeal_pending` |
| created_at | timestamptz |

### Supporting tables
- `retrieval_event` — `(meme_id, user_id, query_text, chosen_rank, created_at)`;
  relevance/popularity feed (§3.1).
- `policy_documents` — versioned markdown body of `/policy` (§5.7).
- `illegal_hashes` — maintained blocklist of `file_hash` values (§5.3).

## State machine (§4)

```
        submit (private)              /suggest
 (new) ───────────────► private ───────────────► pending
                            │                        │
                     delete (owner/quota)      vote resolves
                            │                    ┌────┴─────┐
                            ▼                    ▼          ▼
                        (deleted)             public     rejected
                                                 │            │
                                     report threshold /   (terminal,
                                     admin / legal          resubmission
                                          │                 allowed after
                                          ▼                 cool-down)
                                       removed
                                          │
                                    appeal window
                              ┌───────────┴───────────┐
                              ▼                        ▼
                         reinstated (public)      removed (terminal)
```

Rules:
- `private → public` directly is **not allowed** — everything public passed
  through a vote (no admin addition shortcut).
- `rejected` memes can be re-submitted once after a cool-down
  (`RESUBMIT_COOLDOWN_DAYS`).
- `removed` memes are hidden from all search/suggest surfaces; media is kept for
  audit/appeal (except illegal content, which is purged from durable storage).
