from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from worker.resource_limits import BoundedTaskExecutor, positive_int_env


def test_bounded_executor_rejects_overlap_and_excess_queue() -> None:
    executor = BoundedTaskExecutor(max_workers=1, max_pending=1)
    first_started = threading.Event()
    release_first = threading.Event()
    second_finished = threading.Event()

    def first() -> None:
        first_started.set()
        assert release_first.wait(timeout=2)

    try:
        assert executor.submit("profile:1", first)
        assert first_started.wait(timeout=2)
        assert not executor.submit("profile:1", lambda: None)
        assert executor.submit("profile:2", second_finished.set)
        assert not executor.submit("profile:3", lambda: None)

        release_first.set()
        assert second_finished.wait(timeout=2)
    finally:
        release_first.set()
        executor.shutdown()


def test_bounded_executor_survives_task_exception() -> None:
    executor = BoundedTaskExecutor(max_workers=1, max_pending=1)
    failed = threading.Event()
    recovered = threading.Event()

    def fail() -> None:
        failed.set()
        raise RuntimeError("expected test failure")

    try:
        assert executor.submit("failing", fail)
        assert failed.wait(timeout=2)
        assert executor.submit("next", recovered.set)
        assert recovered.wait(timeout=2)
    finally:
        executor.shutdown()


def test_positive_int_env_falls_back_for_invalid_values(monkeypatch) -> None:
    monkeypatch.setenv("WORKER_TEST_LIMIT", "0")
    assert positive_int_env("WORKER_TEST_LIMIT", 7) == 7

    monkeypatch.setenv("WORKER_TEST_LIMIT", "not-a-number")
    assert positive_int_env("WORKER_TEST_LIMIT", 7) == 7

    monkeypatch.setenv("WORKER_TEST_LIMIT", "3")
    assert positive_int_env("WORKER_TEST_LIMIT", 7) == 3


def _statement_limit(statement) -> int:
    return statement._limit_clause.value


def test_ai_analysis_query_is_batched(monkeypatch) -> None:
    from worker.ingest import run_ai_analysis_for_new_matches

    monkeypatch.setenv("DEEPSEEK_TOKEN", "configured")
    session = MagicMock()
    session.execute.return_value.scalars.return_value = []

    with patch("worker.ingest.AI_ANALYSIS_BATCH_SIZE", 3):
        run_ai_analysis_for_new_matches(session, "goszakupki_by")

    assert _statement_limit(session.execute.call_args.args[0]) == 3


def test_routing_query_is_batched() -> None:
    from worker.routing import run_local_profile_routing

    session = MagicMock()
    session.execute.return_value.scalars.return_value = []

    with patch("worker.routing.ROUTING_BATCH_SIZE", 4):
        run_local_profile_routing(session)

    assert _statement_limit(session.execute.call_args.args[0]) == 4


def test_results_query_is_batched() -> None:
    from worker.ingest import check_results_for_active_tenders

    session = MagicMock()
    session.scalars.return_value.all.return_value = []

    with patch("worker.ingest.RESULTS_CHECK_BATCH_SIZE", 5):
        check_results_for_active_tenders(session)

    assert _statement_limit(session.scalars.call_args.args[0]) == 5


def test_notification_query_is_batched() -> None:
    from worker.notifications import dispatch_notifications

    session = MagicMock()
    session.execute.return_value.scalars.return_value = []

    with patch("worker.notifications.NOTIFICATION_BATCH_SIZE", 6):
        dispatch_notifications(session)

    assert _statement_limit(session.execute.call_args.args[0]) == 6
