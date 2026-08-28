"""SQLAlchemy models for the MemeBot domain (spec §2)."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.schema import Computed

from app.enums import (
    MediaType,
    RemovalDecision,
    RemovalTrigger,
    ReportReason,
    SubmissionStatus,
    Visibility,
    VoteValue,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    locale: Mapped[str] = mapped_column(String(16), default="en")
    private_quota: Mapped[int] = mapped_column(Integer, default=200)
    trust_score: Mapped[int] = mapped_column(Integer, default=100)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    memes: Mapped[list["Meme"]] = relationship(back_populates="owner")


class Meme(Base):
    __tablename__ = "memes"
    __table_args__ = (
        Index("ix_memes_tags", "tags", postgresql_using="gin"),
        Index("ix_memes_file_hash", "file_hash"),
        Index("ix_memes_visibility", "visibility"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    visibility: Mapped[Visibility] = mapped_column(
        SAEnum(Visibility, name="visibility"), default=Visibility.PRIVATE, nullable=False
    )
    media_type: Mapped[MediaType] = mapped_column(
        SAEnum(MediaType, name="media_type"), nullable=False
    )
    telegram_file_id: Mapped[str] = mapped_column(Text, nullable=False)
    storage_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    language: Mapped[str] = mapped_column(String(16), default="en")
    nsfw: Mapped[bool] = mapped_column(Boolean, default=False)
    downvotes: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Generated tsvector for full-text search (spec §6.1 tier 2).
    search_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(description,''))",
            persisted=True,
        ),
        nullable=True,
    )
    popularity: Mapped[float] = mapped_column(Float, default=0.0)

    owner: Mapped["User | None"] = relationship(back_populates="memes")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="meme")
    reports: Mapped[list["Report"]] = relationship(back_populates="meme")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("meme_id", name="uq_submission_meme"),
        Index("ix_submissions_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    meme_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memes.id", ondelete="CASCADE"), nullable=False
    )
    submitter_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[SubmissionStatus] = mapped_column(
        SAEnum(SubmissionStatus, name="submission_status"),
        default=SubmissionStatus.OPEN,
        nullable=False,
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    meme: Mapped["Meme"] = relationship(back_populates="submissions")
    votes: Mapped[list["Vote"]] = relationship(back_populates="submission")


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("submission_id", "voter_id", name="uq_vote_submission_voter"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    submission_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
    voter_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[VoteValue] = mapped_column(
        SAEnum(VoteValue, name="vote_value"), nullable=False
    )
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    submission: Mapped["Submission"] = relationship(back_populates="votes")


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_meme_reason", "meme_id", "reason"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    meme_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memes.id", ondelete="CASCADE"), nullable=False
    )
    reporter_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[ReportReason] = mapped_column(
        SAEnum(ReportReason, name="report_reason"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    meme: Mapped["Meme"] = relationship(back_populates="reports")


class RemovalCase(Base):
    __tablename__ = "removal_cases"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    meme_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memes.id", ondelete="CASCADE"), nullable=False
    )
    trigger: Mapped[RemovalTrigger] = mapped_column(
        SAEnum(RemovalTrigger, name="removal_trigger"), nullable=False
    )
    policy_clause: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[RemovalDecision] = mapped_column(
        SAEnum(RemovalDecision, name="removal_decision"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RetrievalEvent(Base):
    __tablename__ = "retrieval_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    meme_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    query_text: Mapped[str] = mapped_column(Text, default="")
    chosen_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PolicyDocument(Base):
    """Versioned governance policy text (spec §5.7)."""

    __tablename__ = "policy_documents"

    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class IllegalHash(Base):
    """Maintained illegal-content blocklist (spec §5.3)."""

    __tablename__ = "illegal_hashes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
