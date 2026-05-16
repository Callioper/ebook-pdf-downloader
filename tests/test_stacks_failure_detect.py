import pytest
from engine.aa_downloader import _detect_stacks_failure

MD5 = "b199088731ad6191afcde1e6d21b7254"


def test_detect_failure_current_item():
    """Failure on the `current` item with failed_at + error."""
    data = {
        "current": {
            "md5": MD5,
            "failed_at": "2026-05-16T20:49:39",
            "error": "Mirror annas-archive.pk failed",
            "status": "failed",
        },
        "queue": [],
        "recent_history": [],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg is not None
    assert "annas-archive.pk" in msg


def test_detect_failure_queue_item():
    """Failure on a queue item."""
    data = {
        "current": None,
        "queue": [
            {
                "md5": MD5,
                "failed_at": "2026-05-16T20:49:39",
                "error_message": "Got 403 but no FlareSolverr configured",
                "status": "failed",
            }
        ],
        "recent_history": [],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg is not None
    assert "403" in msg


def test_detect_failure_history_item():
    """Failure in recent_history."""
    data = {
        "current": None,
        "queue": [],
        "recent_history": [
            {
                "md5": MD5,
                "failed_at": "2026-05-16T20:49:39",
                "error": "Download timeout",
                "status": "failed",
            }
        ],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg is not None
    assert "timeout" in msg


def test_no_failure_no_matching_md5():
    """Item exists but is not failed — no match returned."""
    data = {
        "current": {
            "md5": MD5,
            "progress": {"percent": 45, "speed": 102400, "downloaded": 1000000, "total_size": 2000000},
        },
        "queue": [],
        "recent_history": [],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg is None


def test_no_failure_different_md5():
    """A different MD5 failed — our MD5 should not match."""
    data = {
        "current": {
            "md5": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "failed_at": "2026-05-16T20:49:39",
            "error": "some other failure",
        },
        "queue": [],
        "recent_history": [],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg is None


def test_no_failure_status_not_failed():
    """Item has no failed_at and status is not 'failed'."""
    data = {
        "current": {
            "md5": MD5,
            "status": "downloading",
            "progress": {"percent": 70},
        },
        "queue": [],
        "recent_history": [],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg is None


def test_no_failure_empty_status():
    data = {"current": None, "queue": [], "recent_history": []}
    msg = _detect_stacks_failure(data, MD5)
    assert msg is None


def test_no_failure_missing_keys():
    data = {}
    msg = _detect_stacks_failure(data, MD5)
    assert msg is None


def test_detect_failure_fallback_to_status_message():
    """When `error` is absent but `status_message` says 'failed'."""
    data = {
        "current": {
            "md5": MD5,
            "failed_at": "2026-05-16T20:49:39",
            "status_message": "Mirror download failed",
        },
        "queue": [],
        "recent_history": [],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg is not None
    assert "Mirror download failed" in msg


def test_detect_failure_fallback_to_message_field():
    """When all other fields absent but `message` field exists."""
    data = {
        "queue": [
            {
                "md5": MD5,
                "failed_at": "2026-05-16T20:49:39",
                "message": "transfer: Connection refused",
            }
        ],
        "current": None,
        "recent_history": [],
    }
    msg = _detect_stacks_failure(data, MD5)
    assert msg is not None
    assert "Connection refused" in msg
