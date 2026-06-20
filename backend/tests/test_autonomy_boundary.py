"""Tests for the autonomy-boundary classifier (TASK-050, §19.2 TK3)."""

import pytest
from unittest.mock import patch

from app.loaders.task_classify import assert_auto_eligible, classify_execution_mode
from app.models.enums import ExecutionMode, TaskKind

_AUTO_KINDS = [
    TaskKind.RESEARCH,
    TaskKind.NEWS_GATHER,
    TaskKind.SWAP_CANDIDATES,
    TaskKind.DRAFT_PREP,
    TaskKind.ANALYSIS,
]

_MANUAL_KINDS = [
    TaskKind.CONTACT_CLIENT,
    TaskKind.PLACE_ORDER,
    TaskKind.SEND_MESSAGE,
    TaskKind.CRM_WRITEBACK,
]


@pytest.mark.parametrize("kind", _AUTO_KINDS)
def test_auto_eligible_kinds_return_auto(kind):
    assert classify_execution_mode(kind) == ExecutionMode.AUTO


@pytest.mark.parametrize("kind", _MANUAL_KINDS)
def test_manual_forced_kinds_return_manual(kind):
    assert classify_execution_mode(kind) == ExecutionMode.MANUAL


def test_assert_passes_silently_for_auto_kind():
    assert_auto_eligible(TaskKind.RESEARCH)  # must not raise


@pytest.mark.parametrize("kind", _MANUAL_KINDS)
def test_assert_raises_for_outward_kinds(kind):
    with patch("app.loaders.task_classify.log") as mock_log:
        with pytest.raises(ValueError, match="cannot auto-run"):
            assert_auto_eligible(kind)
        mock_log.warning.assert_called_once()
        event = mock_log.warning.call_args[0][0]
        assert event == "autonomy.boundary_violation"


def test_assert_includes_context_in_log():
    with patch("app.loaders.task_classify.log") as mock_log:
        with pytest.raises(ValueError):
            assert_auto_eligible(TaskKind.PLACE_ORDER, context={"client_id": "abc-123"})
        _, kwargs = mock_log.warning.call_args
        assert kwargs.get("client_id") == "abc-123"
