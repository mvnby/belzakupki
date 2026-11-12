from datetime import datetime, timezone
from unittest.mock import MagicMock

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from belzakupki_db.base import Base
from belzakupki_db.models import SearchProfile, Tenant
from worker import tasks


SOURCES = ("goszakupki_by", "icetrade_by", "butb_by", "gias_by")
PREVIOUS_RUN = datetime(2020, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'pipeline.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as session:
        session.add(SearchProfile(id=1, name="HVAC", is_active=True, last_run_at=PREVIOUS_RUN))
        session.commit()

    calls = []
    failures = {}

    def stage(name):
        def run(session, *args, **kwargs):
            calls.append(name)
            session.add(Tenant(name=name))
            if failures.get(name) == "database":
                # A failed flush poisons the session until the task rolls back.
                session.add(Tenant(name=None))
                session.flush()
            if failures.get(name) == "http":
                request = httpx.Request("GET", "https://icetrade.by/")
                raise httpx.HTTPStatusError("403 Forbidden", request=request,
                                            response=httpx.Response(403, request=request))
        return run

    for source, function in zip(SOURCES, ("ingest_goszakupki_tenders", "ingest_icetrade_tenders",
                                         "ingest_butb_tenders", "ingest_gias_tenders")):
        monkeypatch.setattr(tasks, function, stage(f"ingest:{source}"))
    monkeypatch.setattr(tasks, "_drain_ai_analysis",
                        lambda session, source: stage(f"ai:{source}")(session))
    monkeypatch.setattr(tasks, "run_local_profile_routing", stage("routing"))
    monkeypatch.setattr(tasks, "dispatch_notifications", stage("notify"))
    monkeypatch.setattr(tasks, "SessionLocal", sessions)
    redis = MagicMock()
    monkeypatch.setattr(tasks, "get_redis", lambda: redis)
    yield sessions, calls, failures, redis
    engine.dispose()


def run_pipeline(kind):
    if kind == "profile":
        tasks.run_profile_task_job(1)
    else:
        tasks.run_ingest_task_job()


@pytest.mark.parametrize("kind", ["global", "profile"])
@pytest.mark.parametrize("failure", ["http", "database"])
def test_failed_source_preserves_successful_work_and_runs_remaining_stages(pipeline, kind, failure):
    sessions, calls, failures, redis = pipeline
    failures["ingest:icetrade_by"] = failure

    with pytest.raises(tasks.PipelineIncompleteError, match="ingest:icetrade_by"):
        run_pipeline(kind)

    expected = [f"ingest:{source}" for source in SOURCES]
    if kind == "global":
        expected.append("routing")
    expected += [f"ai:{source}" for source in SOURCES] + ["notify"]
    assert calls == expected
    with sessions() as session:
        # Data before and after the failure survive; the failing stage rolls back.
        assert set(session.scalars(select(Tenant.name))) == set(expected) - {"ingest:icetrade_by"}
        assert session.get(SearchProfile, 1).last_run_at == PREVIOUS_RUN.replace(tzinfo=None)
    if kind == "global":
        redis.set.assert_called_with("belzakupki:task:ingest:global", "idle")


@pytest.mark.parametrize("kind", ["global", "profile"])
def test_failed_ai_source_does_not_starve_other_ai_sources_or_notifications(pipeline, kind):
    sessions, calls, failures, _ = pipeline
    failures["ai:icetrade_by"] = "database"
    with pytest.raises(tasks.PipelineIncompleteError, match="ai:icetrade_by"):
        run_pipeline(kind)
    assert calls[-5:] == [f"ai:{source}" for source in SOURCES] + ["notify"]
    with sessions() as session:
        names = set(session.scalars(select(Tenant.name)))
        assert "ai:icetrade_by" not in names
        assert {"ai:butb_by", "ai:gias_by", "notify"} <= names
        assert session.get(SearchProfile, 1).last_run_at == PREVIOUS_RUN.replace(tzinfo=None)


def test_routing_failure_still_runs_ai_and_notifications(pipeline):
    sessions, calls, failures, _ = pipeline
    failures["routing"] = "database"
    with pytest.raises(tasks.PipelineIncompleteError, match="routing"):
        tasks.run_ingest_task_job()
    with sessions() as session:
        assert "routing" not in set(session.scalars(select(Tenant.name)))
        assert "notify" in set(session.scalars(select(Tenant.name)))


@pytest.mark.parametrize("kind", ["global", "profile"])
def test_complete_pipeline_succeeds_and_only_then_stamps_profile(pipeline, kind):
    sessions, calls, _, redis = pipeline
    run_pipeline(kind)
    with sessions() as session:
        assert set(session.scalars(select(Tenant.name))) == set(calls)
        last_run = session.get(SearchProfile, 1).last_run_at
        if kind == "profile":
            assert last_run > PREVIOUS_RUN.replace(tzinfo=None)
        else:
            assert last_run == PREVIOUS_RUN.replace(tzinfo=None)
            redis.set.assert_called_with("belzakupki:task:ingest:global", "idle")
