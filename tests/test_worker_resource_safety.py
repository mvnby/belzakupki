from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest
from rq.exceptions import DuplicateJobError

from worker.resource_limits import positive_int_env


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

    statement = session.execute.call_args.args[0]
    assert _statement_limit(statement) == 6
    assert "tender_matches.ai_relevance IS true" in str(statement)


def test_scheduler_job_is_unique_and_deterministic() -> None:
    from worker.scheduler import enqueue_scheduled_job

    queue = MagicMock()
    queue.__len__.return_value = 0

    assert enqueue_scheduled_job(
        queue,
        key="profile-42",
        function="worker.tasks.run_profile_task_job",
        args=(42,),
    )

    call = queue.enqueue_call.call_args
    assert call.kwargs["func"] == "worker.tasks.run_profile_task_job"
    assert call.kwargs["args"] == (42,)
    assert call.kwargs["job_id"] == "belzakupki-scheduled-profile-42"
    assert call.kwargs["unique"] is True
    assert call.kwargs["timeout"] == 3600
    assert call.kwargs["result_ttl"] == 0
    assert call.kwargs["failure_ttl"] == 300
    assert call.kwargs["retry"].max == 3
    assert call.kwargs["retry"].intervals == [60, 300, 900]

    queue.enqueue_call.side_effect = DuplicateJobError("already active")
    assert not enqueue_scheduled_job(
        queue,
        key="profile-42",
        function="worker.tasks.run_profile_task_job",
        args=(42,),
    )


def test_scheduler_defers_when_queue_is_full() -> None:
    from worker.scheduler import enqueue_scheduled_job

    queue = MagicMock()
    queue.__len__.return_value = 2
    with patch("worker.scheduler.MAX_PENDING_JOBS", 2):
        assert not enqueue_scheduled_job(
            queue,
            key="global-ingest",
            function="worker.tasks.run_ingest_task_job",
        )
    queue.enqueue_call.assert_not_called()


@patch("worker.tasks.dispatch_notifications")
@patch("worker.tasks._drain_all_ai_analysis")
@patch("worker.tasks.ingest_gias_tenders")
@patch("worker.tasks.ingest_butb_tenders")
@patch("worker.tasks.ingest_icetrade_tenders")
@patch("worker.tasks.ingest_goszakupki_tenders")
@patch("worker.tasks.SessionLocal")
def test_profile_stamp_happens_only_after_success(
    session_local,
    ingest_goszakupki,
    ingest_icetrade,
    ingest_butb,
    ingest_gias,
    drain_ai,
    dispatch,
) -> None:
    from worker.tasks import run_profile_task_job

    profile = MagicMock(id=42, is_active=True, last_run_at=None)
    session = session_local.return_value.__enter__.return_value
    session.query.return_value.filter.return_value.one_or_none.return_value = profile
    session.get.return_value = profile

    ingest_goszakupki.side_effect = lambda *args, **kwargs: (
        profile.last_run_at is None
        or pytest.fail("profile stamped before pipeline completed")
    )
    dispatch.side_effect = lambda *args, **kwargs: (
        profile.last_run_at is None
        or pytest.fail("profile stamped before notifications completed")
    )

    run_profile_task_job(42)

    assert profile.last_run_at is not None
    session.add.assert_called_with(profile)


@patch("worker.tasks.ingest_goszakupki_tenders", side_effect=RuntimeError("crawl failed"))
@patch("worker.tasks.SessionLocal")
def test_failed_profile_pipeline_is_not_stamped(session_local, ingest) -> None:
    from worker.tasks import run_profile_task_job

    profile = MagicMock(id=42, is_active=True, last_run_at=None)
    session = session_local.return_value.__enter__.return_value
    session.query.return_value.filter.return_value.one_or_none.return_value = profile

    with pytest.raises(RuntimeError, match="crawl failed"):
        run_profile_task_job(42)

    assert profile.last_run_at is None


def test_rq_entrypoint_starts_no_application_threads() -> None:
    import apps.worker.main as worker_main

    source = inspect.getsource(worker_main)
    assert "threading" not in source
    assert "start_scheduler" not in source
    assert "start_telegram_bot_listener" not in source
    assert "worker.work(with_scheduler=True)" in source


def test_ai_snapshot_drains_across_multiple_bounded_batches() -> None:
    from worker.ingest import AIAnalysisBatch
    from worker.tasks import _drain_ai_analysis

    session = MagicMock()
    batches = [
        AIAnalysisBatch(selected_count=10, last_selected_id=10),
        AIAnalysisBatch(selected_count=10, last_selected_id=20),
        AIAnalysisBatch(selected_count=5, last_selected_id=25),
    ]
    with (
        patch("worker.tasks.get_pending_ai_analysis_max_id", return_value=25),
        patch("worker.tasks.run_ai_analysis_for_new_matches", side_effect=batches) as run,
    ):
        assert _drain_ai_analysis(session, "goszakupki_by") == 25

    assert [call.kwargs["after_id"] for call in run.call_args_list] == [0, 10, 20]
    assert all(call.kwargs["through_id"] == 25 for call in run.call_args_list)
    assert session.commit.call_count == 3
    assert session.expunge_all.call_count == 3


def test_failed_ai_rows_advance_cursor_without_starving_later_ids(monkeypatch) -> None:
    from worker.ingest import run_ai_analysis_for_new_matches

    monkeypatch.setenv("DEEPSEEK_TOKEN", "configured")
    matches = []
    for match_id in (1, 2, 3):
        match = MagicMock(id=match_id)
        match.tender.title = f"Tender {match_id}"
        match.tender.customer_name = "Customer"
        match.tender.description = "Description"
        match.profile.niche_description = "Niche"
        match.profile.keywords = []
        match.profile.negative_keywords = []
        match.profile.tenant_id = None
        matches.append(match)

    session = MagicMock()
    session.execute.return_value.scalars.return_value = matches
    with patch(
        "worker.analyzer.deepseek_client.analyze_relevance_by_metadata",
        return_value=None,
    ):
        batch = run_ai_analysis_for_new_matches(
            session,
            "goszakupki_by",
            after_id=0,
            through_id=3,
        )

    assert batch.selected_count == 3
    assert batch.last_selected_id == 3


def test_no_ai_token_explicitly_approves_the_bounded_batch(monkeypatch) -> None:
    from worker.ingest import run_ai_analysis_for_new_matches

    monkeypatch.delenv("DEEPSEEK_TOKEN", raising=False)
    matches = [MagicMock(id=1), MagicMock(id=2)]
    session = MagicMock()
    session.execute.return_value.scalars.return_value = matches

    batch = run_ai_analysis_for_new_matches(
        session,
        "goszakupki_by",
        after_id=0,
        through_id=2,
    )

    assert batch.selected_count == 2
    assert batch.last_selected_id == 2
    for match in matches:
        assert match.ai_relevance is True
        assert match.ai_analysis["bypassed"] is True
        assert match.ai_analysis["reason"] == "ai_not_configured"
    assert session.add.call_count == 2
    session.flush.assert_called_once_with()


def test_no_ai_token_drain_continues_after_first_batch(monkeypatch) -> None:
    from worker.tasks import _drain_ai_analysis

    monkeypatch.delenv("DEEPSEEK_TOKEN", raising=False)
    first_batch = [MagicMock(id=value) for value in range(1, 11)]
    second_batch = [MagicMock(id=value) for value in range(11, 16)]
    first_result = MagicMock()
    first_result.scalars.return_value = first_batch
    second_result = MagicMock()
    second_result.scalars.return_value = second_batch
    session = MagicMock()
    session.execute.side_effect = [first_result, second_result]

    with patch("worker.tasks.get_pending_ai_analysis_max_id", return_value=15):
        assert _drain_ai_analysis(session, "goszakupki_by") == 15

    assert all(match.ai_relevance is True for match in first_batch + second_batch)
    assert session.commit.call_count == 2
    assert session.expunge_all.call_count == 2


def test_notification_drain_continues_after_zero_dispatch_batch() -> None:
    from worker.notifications import dispatch_notifications

    session = MagicMock()
    # The first 50 selected rows can all be expired or have no channel. The
    # drain must use selected_count, not dispatched_count, to continue.
    with patch(
        "worker.notifications._dispatch_notification_batch",
        side_effect=[(50, 0), (30, 30), (0, 0)],
    ) as dispatch_batch:
        assert dispatch_notifications(session, drain=True) == 30

    assert dispatch_batch.call_count == 3
    assert session.expunge_all.call_count == 2


def test_results_snapshot_drain_does_not_starve_after_no_result_batch() -> None:
    from worker.ingest import ResultsCheckBatch
    from worker.tasks import _drain_results_check

    session = MagicMock()
    batches = [
        ResultsCheckBatch(selected_count=50, last_selected_id=50),
        ResultsCheckBatch(selected_count=30, last_selected_id=80),
    ]
    with (
        patch("worker.tasks.get_pending_results_max_id", return_value=80),
        patch("worker.tasks.check_results_for_active_tenders", side_effect=batches) as check,
    ):
        assert _drain_results_check(session) == 80

    assert [call.kwargs["after_id"] for call in check.call_args_list] == [0, 50]
    assert all(call.kwargs["through_id"] == 80 for call in check.call_args_list)
    assert session.expunge_all.call_count == 2
