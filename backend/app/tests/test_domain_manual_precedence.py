from datetime import datetime, timedelta, timezone

from app.domain.manual_precedence import may_automated_observation_supersede_manual


def _at(h):
    return datetime(2026, 3, 4, h, 0, tzinfo=timezone.utc)


def test_no_manual_observation_exists_automated_may_be_accepted():
    assert may_automated_observation_supersede_manual(
        lock_manual=False, manual_recorded_at=None, automated_timestamp=_at(10)
    ) is True


def test_automated_older_than_manual_must_not_supersede():
    assert may_automated_observation_supersede_manual(
        lock_manual=False, manual_recorded_at=_at(12), automated_timestamp=_at(10)
    ) is False


def test_automated_same_timestamp_as_manual_must_not_supersede():
    assert may_automated_observation_supersede_manual(
        lock_manual=False, manual_recorded_at=_at(12), automated_timestamp=_at(12)
    ) is False


def test_automated_strictly_newer_than_manual_may_supersede():
    assert may_automated_observation_supersede_manual(
        lock_manual=False, manual_recorded_at=_at(12), automated_timestamp=_at(13)
    ) is True


def test_lock_manual_blocks_even_a_much_newer_automated_observation():
    much_later = _at(12) + timedelta(days=30)
    assert may_automated_observation_supersede_manual(
        lock_manual=True, manual_recorded_at=_at(12), automated_timestamp=much_later
    ) is False


def test_lock_manual_blocks_even_when_no_manual_timestamp_recorded_yet():
    """A defensive edge case: if lock_manual is somehow set with no
    manual observation on record, the lock still wins -- it must never
    be interpreted as "nothing to protect, so allow.\""""
    assert may_automated_observation_supersede_manual(
        lock_manual=True, manual_recorded_at=None, automated_timestamp=_at(10)
    ) is False
