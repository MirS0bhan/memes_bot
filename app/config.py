"""Application configuration loaded from environment (12-factor, spec §7.4).

All policy thresholds (spec §5.2 / §5.5) are env-configurable so they can be
tuned without a redeploy.
"""

from functools import lru_cache
from typing import Callable

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import EnvSettingsSource


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ── Core ──────────────────────────────────────────────────────────────
    bot_token: str = Field(..., alias="BOT_TOKEN")
    bot_username: str = Field(default="", alias="BOT_USERNAME")

    admin_users: list[int] = Field(default_factory=list, alias="ADMIN_USERS")
    illegal_hashes: list[str] = Field(default_factory=list, alias="ILLEGAL_HASHES")

    @field_validator("admin_users", mode="before")
    @classmethod
    def _parse_admin_users(cls, v: object) -> object:
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    @field_validator("illegal_hashes", mode="before")
    @classmethod
    def _parse_illegal_hashes(cls, v: object) -> object:
        if isinstance(v, str):
            return [h.strip().lower() for h in v.split(",") if h.strip()]
        return v

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # Parse comma-separated list env vars ourselves so empty strings -> [].
        # pydantic-settings would otherwise json.loads() the raw value and fail.
        return (
            init_settings,
            cls._ListEnvSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )


    class _ListEnvSource(EnvSettingsSource):
        def prepare_field_value(self, field_name, field, field_value, value_is_complex):
            if field_name in ("admin_users", "illegal_hashes") and isinstance(field_value, str):
                parts = [x.strip() for x in field_value.split(",") if x.strip()]
                if field_name == "admin_users":
                    return [int(x) for x in parts]
                return [p.lower() for p in parts]
            return super().prepare_field_value(field_name, field, field_value, value_is_complex)

    database_url: str = Field(
        default="postgresql+asyncpg://memebot:memebot@localhost:5432/memebot",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # ── Runtime role ──────────────────────────────────────────────────────
    # "web" = webhook/polling handler, "worker" = scheduled jobs, "both" = all.
    role: str = Field(default="both", alias="ROLE")

    # ── Webhook ─────────────────────────────────────────────────────────────
    webhook_url: str | None = Field(default=None, alias="WEBHOOK_URL")
    webhook_path: str = Field(default="/webhook", alias="WEBHOOK_PATH")
    webhook_secret: str = Field(default="", alias="WEBHOOK_SECRET")
    listen_host: str = Field(default="0.0.0.0", alias="LISTEN_HOST")
    listen_port: int = Field(default=8080, alias="LISTEN_PORT")

    # ── Public pool / voting policy (spec §5.2) ─────────────────────────────
    vote_window_hours: int = Field(default=48, alias="VOTE_WINDOW_HOURS")
    approve_net_score: int = Field(default=10, alias="APPROVE_NET_SCORE")
    approve_min_upvotes: int = Field(default=5, alias="APPROVE_MIN_UPVOTES")
    reject_net_score: int = Field(default=-5, alias="REJECT_NET_SCORE")
    nsfw_approve_net_score: int = Field(default=20, alias="NSFW_APPROVE_NET_SCORE")
    resubmit_cooldown_days: int = Field(default=30, alias="RESUBMIT_COOLDOWN_DAYS")

    # ── Removal policy (spec §5.5) ────────────────────────────────────────
    report_threshold: int = Field(default=5, alias="REPORT_THRESHOLD")
    report_window_hours: int = Field(default=72, alias="REPORT_WINDOW_HOURS")
    review_vote_window_hours: int = Field(default=24, alias="REVIEW_VOTE_WINDOW_HOURS")
    appeal_window_days: int = Field(default=7, alias="APPEAL_WINDOW_DAYS")

    # ── Trust / weighting (spec §5.4) ──────────────────────────────────────
    new_account_age_days: int = Field(default=1, alias="NEW_ACCOUNT_AGE_DAYS")
    new_account_weight: float = Field(default=0.5, alias="NEW_ACCOUNT_WEIGHT")
    established_weight: float = Field(default=1.0, alias="ESTABLISHED_WEIGHT")
    penalized_weight: float = Field(default=0.25, alias="PENALIZED_WEIGHT")
    established_age_days: int = Field(default=30, alias="ESTABLISHED_AGE_DAYS")

    # ── Private pool (spec §2 User) ────────────────────────────────────────
    default_private_quota: int = Field(default=200, alias="DEFAULT_PRIVATE_QUOTA")

    # ── Search ranking weights (spec §6.1) ─────────────────────────────────
    rank_text_weight: float = Field(default=1.0, alias="RANK_TEXT_WEIGHT")
    rank_popularity_weight: float = Field(default=0.3, alias="RANK_POPULARITY_WEIGHT")
    rank_recency_weight: float = Field(default=0.2, alias="RANK_RECENCY_WEIGHT")
    rank_report_penalty: float = Field(default=0.5, alias="RANK_REPORT_PENALTY")

    # ── Review channel (spec §3.3 / §5.1) ──────────────────────────────────
    review_channel_id: int | None = Field(default=None, alias="REVIEW_CHANNEL_ID")

    # ── Abuse controls (spec §7.6) ─────────────────────────────────────────
    inline_rate_per_min: int = Field(default=20, alias="INLINE_RATE_PER_MIN")
    suggest_rate_per_hour: int = Field(default=10, alias="SUGGEST_RATE_PER_HOUR")
    report_rate_per_hour: int = Field(default=20, alias="REPORT_RATE_PER_HOUR")

    # ── Object storage fallback (spec §6.2) ───────────────────────────────
    s3_endpoint_url: str | None = Field(default=None, alias="S3_ENDPOINT_URL")
    s3_bucket: str | None = Field(default=None, alias="S3_BUCKET")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_access_key: str | None = Field(default=None, alias="S3_ACCESS_KEY")
    s3_secret_key: str | None = Field(default=None, alias="S3_SECRET_KEY")
    # Durable media store: "s3" if S3 configured, else local filesystem at storage_path.
    storage_path: str = Field(default="./storage", alias="STORAGE_PATH")

    # ── Community downvote removal (spec §5.5.4) ───────────────────────────
    community_downvote_threshold: int = Field(default=20, alias="COMMUNITY_DOWNVOTE_THRESHOLD")

    # ── Metrics (spec §7.5) ────────────────────────────────────────────────
    metrics_port: int = Field(default=9090, alias="METRICS_PORT")

    # ── Misc ───────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    inline_cache_seconds: int = Field(default=300, alias="INLINE_CACHE_SECONDS")


@lru_cache
def get_settings() -> Settings:
    return Settings()
