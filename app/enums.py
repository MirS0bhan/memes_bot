"""Enum definitions for the MemeBot domain model (spec §2)."""

from enum import StrEnum


class Visibility(StrEnum):
    PRIVATE = "private"
    PENDING = "pending"
    PUBLIC = "public"
    REJECTED = "rejected"
    REMOVED = "removed"


class MediaType(StrEnum):
    PHOTO = "photo"
    VIDEO = "video"
    ANIMATION = "animation"
    VOICE = "voice"
    AUDIO = "audio"
    STICKER = "sticker"


class SubmissionStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class VoteValue(StrEnum):
    UP = "up"
    DOWN = "down"


class ReportReason(StrEnum):
    NSFW_UNFLAGGED = "nsfw_unflagged"
    HATE_HARASSMENT = "hate_harassment"
    COPYRIGHT = "copyright"
    SPAM_LOW_QUALITY = "spam_low_quality"
    ILLEGAL = "illegal"
    OTHER = "other"


class RemovalTrigger(StrEnum):
    REPORT_THRESHOLD = "report_threshold"
    ADMIN_MANUAL = "admin_manual"
    LEGAL_REQUEST = "legal_request"
    COMMUNITY_DOWNVOTE = "community_downvote"


class RemovalDecision(StrEnum):
    REMOVED = "removed"
    KEPT = "kept"
    APPEAL_PENDING = "appeal_pending"
