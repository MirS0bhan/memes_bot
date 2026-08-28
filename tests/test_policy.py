"""Policy engine checks (spec §5.2 / §5.4)."""

import datetime
import zoneinfo

import pytest

from app.enums import SubmissionStatus
from app.policy import evaluate_submission, vote_weight


def _user(trust_score=100, age_days=400, banned=False):
    class U:
        pass

    u = U()
    u.trust_score = trust_score
    u.is_banned = banned
    u.created_at = datetime.datetime.now(zoneinfo.ZoneInfo("UTC")) - datetime.timedelta(days=age_days)
    u.username = "x"
    u.telegram_id = 1
    return u


@pytest.mark.parametrize(
    "net,up,nsfw,expected",
    [
        (12, 6, False, SubmissionStatus.APPROVED),
        (8, 6, False, None),  # not decisive
        (-6, 0, False, SubmissionStatus.REJECTED),
        (15, 10, True, None),  # nsfw needs higher bar
        (21, 10, True, SubmissionStatus.APPROVED),
    ],
)
def test_evaluate_submission(net, up, nsfw, expected):
    assert evaluate_submission(net, up, nsfw) == expected


def test_vote_weight():
    assert vote_weight(_user(trust_score=100, age_days=400)) == 1.0
    assert vote_weight(_user(trust_score=10, age_days=400)) == 0.25  # penalized
    assert vote_weight(_user(trust_score=100, age_days=0)) == 0.5  # new account
    assert vote_weight(_user(banned=True)) == 0.0
