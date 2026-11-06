from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from belzakupki_db.base import Base
from belzakupki_db.billing import (
    check_and_reset_billing_cycle, increment_ai_credits, reserve_ai_credit,
)
from belzakupki_db.models import (
    Tenant, TenderSource, Tender, SearchProfile, TenderMatch,
    NotificationChannel, NotificationLog,
)
from belzakupki_db.presets import PRESETS
from worker import notifications
from worker.ingest import resolve_profile_niche, run_ai_analysis_for_new_matches


@pytest.fixture
def postgres_schema():
    raw = os.getenv("TEST_POSTGRES_URL")
    if not raw:
        pytest.skip("TEST_POSTGRES_URL is required for PostgreSQL concurrency/migration checks")
    url = make_url(raw)
    # Never create/drop test schemas in an accidentally supplied live database.
    assert url.database == "belzakupki_test"
    schema = "reliability_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url.update_query_dict({"options": f"-csearch_path={schema}"}))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture(params=["sqlite", "postgres"])
def database(request, tmp_path):
    if request.param == "postgres":
        engine = request.getfixturevalue("postgres_schema")
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'reliability.sqlite'}")
        # SQLite's legacy transaction mode would otherwise commit a top-level
        # SAVEPOINT independently of the Session's surrounding transaction.
        @event.listens_for(engine, "connect")
        def explicit_transactions(connection, _):
            connection.isolation_level = None
        @event.listens_for(engine, "begin")
        def begin(connection):
            connection.exec_driver_sql("BEGIN")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def seed(session, *, credits=2, count=1, channels=0, confirmed=False, **tenant_options):
    tenant = Tenant(name="Test", plan="starter", ai_credits_used=credits, **tenant_options)
    source = session.scalar(select(TenderSource).where(TenderSource.code == "gias_by"))
    if source is None:
        source = TenderSource(code="gias_by", name="Test", base_url="https://example.org")
        session.add(source)
    session.add(tenant)
    session.flush()
    profile = SearchProfile(tenant_id=tenant.id, name="Office", preset_code="office_supplies",
                            keywords=["бумага"], min_score=1)
    session.add(profile)
    session.flush()
    matches = []
    for _ in range(count):
        tender = Tender(source_id=source.id, external_id=uuid4().hex,
                        title="Поставка офисной бумаги", url="https://example.org/tender",
                        deadline_at=datetime.now(timezone.utc) + timedelta(days=1))
        session.add(tender)
        session.flush()
        match = TenderMatch(tender_id=tender.id, profile_id=profile.id, score=80,
                            matched_keywords=["бумага"], ai_relevance=True if confirmed else None)
        session.add(match)
        matches.append(match)
    for i in range(channels):
        session.add(NotificationChannel(profile_id=profile.id, name=str(i), type="telegram",
                                        config={"chat_id": str(i + 1)}))
    session.commit()
    return tenant, matches


@pytest.mark.parametrize("explicit,preset,keywords,expected", [
    ("  своя ниша  ", "hvac", ["бумага"], "своя ниша"),
    (" ", "office_supplies", [], PRESETS["office_supplies"]["description"]),
    (None, "custom", [" бумага ", "ручки"], "Поиск тендеров по ключевым словам: бумага, ручки"),
    (None, "unknown", ["бумага"], "Поиск тендеров по ключевым словам: бумага"),
    (None, None, [], "Общий поиск тендеров без заданной отраслевой специализации"),
])
def test_profile_niche(explicit, preset, keywords, expected):
    assert resolve_profile_niche(SimpleNamespace(
        niche_description=explicit, preset_code=preset, keywords=keywords,
    )) == expected


@pytest.mark.parametrize("stage_one,stage_two,spent,relevance", [
    (None, None, 0, None),
    (RuntimeError("provider unavailable"), None, 0, None),
    ({"relevant": True}, None, 0, None),
    ({"relevant": True}, RuntimeError("provider unavailable"), 0, None),
    ({"relevant": False}, None, 1, False),
    ({"relevant": True}, {"relevant": False}, 1, False),
    ({"relevant": True}, {"relevant": True}, 1, True),
])
def test_analysis_charges_one_completed_match(database, monkeypatch, stage_one, stage_two, spent, relevance):
    from worker.analyzer import deepseek_client
    first = Mock(side_effect=stage_one) if isinstance(stage_one, Exception) else Mock(return_value=stage_one)
    second = Mock(side_effect=stage_two) if isinstance(stage_two, Exception) else Mock(return_value=stage_two)
    monkeypatch.setattr(deepseek_client, "is_ai_provider_configured", lambda: True)
    monkeypatch.setattr(deepseek_client, "analyze_relevance_by_metadata", first)
    monkeypatch.setattr(deepseek_client, "analyze_tender_relevance", second)
    with Session(database) as session:
        tenant, matches = seed(session)
        run_ai_analysis_for_new_matches(session, "gias_by")
        session.commit()
        assert tenant.ai_credits_used == 2 + spent
        assert matches[0].ai_relevance is relevance
    assert first.call_args.kwargs["niche_description"] == PRESETS["office_supplies"]["description"]
    if second.called:
        assert second.call_args.kwargs["niche_description"] == first.call_args.kwargs["niche_description"]


def test_only_remaining_credit_can_start_analysis(database, monkeypatch):
    from worker.analyzer import deepseek_client
    analyze = Mock(return_value={"relevant": False})
    monkeypatch.setattr(deepseek_client, "is_ai_provider_configured", lambda: True)
    monkeypatch.setattr(deepseek_client, "analyze_relevance_by_metadata", analyze)
    with Session(database) as session:
        tenant, matches = seed(session, credits=29, count=2)
        run_ai_analysis_for_new_matches(session, "gias_by")
        session.commit()
        assert tenant.ai_credits_used == 30
        assert matches[1].ai_analysis["limit_exceeded"] is True
    assert analyze.call_count == 1


@pytest.mark.parametrize("options", [{"is_active": False}, {
    "subscription_expires_at": datetime(2020, 1, 1, tzinfo=timezone.utc),
}])
def test_inactive_or_expired_tenant_cannot_reserve(database, options):
    with Session(database) as session:
        tenant, _ = seed(session, **options)
        with reserve_ai_credit(session, tenant.id) as credit:
            assert not credit.available
        session.commit()
        assert tenant.ai_credits_used == 2


def test_credit_and_result_rollback_together(database):
    with Session(database) as session:
        tenant, matches = seed(session)
        tenant_id, match_id = tenant.id, matches[0].id
        with reserve_ai_credit(session, tenant_id) as credit:
            assert credit.available
            matches[0].ai_relevance = False
            credit.consumed = True
        session.rollback()
    with Session(database) as session:
        assert session.get(Tenant, tenant_id).ai_credits_used == 2
        assert session.get(TenderMatch, match_id).ai_relevance is None


@pytest.mark.parametrize("reset_cycle,expected", [(False, 1), (True, 8)])
def test_concurrent_reservations_and_cycle_reset(postgres_schema, reset_cycle, expected):
    Base.metadata.create_all(postgres_schema)
    with Session(postgres_schema) as session:
        tenant, _ = seed(session, credits=29, billing_cycle_started_at=datetime.now(timezone.utc) - timedelta(days=31 if reset_cycle else 1))
        tenant_id = tenant.id
    barrier = Barrier(8)
    def reserve(_):
        with Session(postgres_schema) as session:
            session.get(Tenant, tenant_id)  # Deliberately preload stale state.
            barrier.wait(timeout=10)
            with reserve_ai_credit(session, tenant_id) as credit:
                available = credit.available
                credit.consumed = available
            session.commit()
            return int(available)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(8))) == expected
    with Session(postgres_schema) as session:
        tenant = session.get(Tenant, tenant_id)
        assert tenant.ai_credits_used == (8 if reset_cycle else 30)


def test_stale_billing_status_does_not_reset_new_usage(postgres_schema):
    Base.metadata.create_all(postgres_schema)
    with Session(postgres_schema) as setup:
        tenant, _ = seed(setup, credits=20, billing_cycle_started_at=datetime.now(timezone.utc) - timedelta(days=31))
        tenant_id = tenant.id
    with Session(postgres_schema) as stale, Session(postgres_schema) as worker:
        old = stale.get(Tenant, tenant_id)
        with reserve_ai_credit(worker, tenant_id) as credit:
            assert credit.available
            credit.consumed = True
        worker.commit()
        check_and_reset_billing_cycle(stale, old)
        stale.commit()
        assert old.ai_credits_used == 1


def test_concurrent_analysis_does_not_charge_same_match_twice(postgres_schema, monkeypatch):
    from worker.analyzer import deepseek_client
    Base.metadata.create_all(postgres_schema)
    with Session(postgres_schema) as session:
        tenant, _ = seed(session)
        tenant_id = tenant.id
    entered, release = Event(), Event()
    def hold(**kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return {"relevant": False}
    analyze = Mock(side_effect=hold)
    monkeypatch.setattr(deepseek_client, "is_ai_provider_configured", lambda: True)
    monkeypatch.setattr(deepseek_client, "analyze_relevance_by_metadata", analyze)
    def run():
        with Session(postgres_schema) as session:
            batch = run_ai_analysis_for_new_matches(session, "gias_by")
            session.commit()
            return batch.selected_count
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run)
        try:
            assert entered.wait(timeout=10)
            assert pool.submit(run).result(timeout=5) == 0
        finally:
            release.set()
        assert first.result(timeout=5) == 1
    assert analyze.call_count == 1
    with Session(postgres_schema) as session:
        assert session.get(Tenant, tenant_id).ai_credits_used == 3


def test_increment_ignores_stale_loaded_counter(postgres_schema):
    Base.metadata.create_all(postgres_schema)
    with Session(postgres_schema) as setup:
        tenant, _ = seed(setup)
        tenant_id = tenant.id
    with Session(postgres_schema) as first, Session(postgres_schema) as second:
        first.get(Tenant, tenant_id)
        second.get(Tenant, tenant_id)
        increment_ai_credits(first, tenant_id)
        first.commit()
        increment_ai_credits(second, tenant_id)
        second.commit()
        assert second.get(Tenant, tenant_id).ai_credits_used == 4


@pytest.fixture
def sender(monkeypatch):
    monkeypatch.setenv("WORKER_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(notifications.time, "sleep", lambda _: None)
    send = Mock()
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    return send


def make_due(session):
    for log in session.scalars(select(NotificationLog).where(NotificationLog.status == "error")):
        log.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.commit()


def test_retry_only_failed_channel_and_reuse_log(database, sender):
    def fail_second(token, chat_id, *args):
        if chat_id == "2":
            raise RuntimeError("temporary failure")
    sender.side_effect = fail_second
    with Session(database) as session:
        _, matches = seed(session, channels=2, confirmed=True)
        match_id = matches[0].id
        assert notifications.dispatch_notifications(session, drain=True) == 0
        logs = list(session.scalars(select(NotificationLog).order_by(NotificationLog.channel_id)))
        ids = [log.id for log in logs]
        assert [log.status for log in logs] == ["sent", "error"]
        assert logs[1].next_attempt_at is not None
        assert session.get(TenderMatch, match_id).status == "new"
        assert notifications.dispatch_notifications(session, drain=True) == 0
        assert sender.call_count == 2
        make_due(session)
        sender.reset_mock(side_effect=True)
        assert notifications.dispatch_notifications(session, drain=True) == 1
        assert [call.args[1] for call in sender.call_args_list] == ["2"]
        logs = list(session.scalars(select(NotificationLog).order_by(NotificationLog.channel_id)))
        assert [log.id for log in logs] == ids
        assert [log.attempt_count for log in logs] == [1, 2]
        assert all(log.status == "sent" and log.error_message is None for log in logs)
        assert session.get(TenderMatch, match_id).status == "processed"
        assert notifications.dispatch_notifications(session, drain=True) == 0


def test_failed_batch_does_not_starve_later_matches(database, sender, monkeypatch):
    monkeypatch.setattr(notifications, "NOTIFICATION_BATCH_SIZE", 1)
    sender.side_effect = [RuntimeError("unavailable"), None, None]
    with Session(database) as session:
        seed(session, count=3, channels=1, confirmed=True)
        assert notifications.dispatch_notifications(session, drain=True) == 2
        assert sender.call_count == 3


def test_retries_stop_at_limit(database, sender, monkeypatch):
    monkeypatch.setattr(notifications, "NOTIFICATION_MAX_ATTEMPTS", 2)
    sender.side_effect = RuntimeError("unavailable")
    with Session(database) as session:
        seed(session, channels=1, confirmed=True)
        assert notifications.dispatch_notifications(session, drain=True) == 0
        make_due(session)
        assert notifications.dispatch_notifications(session, drain=True) == 0
        assert notifications.dispatch_notifications(session, drain=True) == 0
        log = session.scalar(select(NotificationLog))
        assert log.attempt_count == 2 and log.next_attempt_at is None
        assert sender.call_count == 2


def test_filters_tenant_expired_and_unconfirmed_matches(database, sender):
    with Session(database) as session:
        tenant, matches = seed(session, count=3, channels=1, confirmed=True)
        tenant_id = tenant.id
        matches[0].tender.deadline_at = datetime.now(timezone.utc) - timedelta(days=1)
        matches[1].ai_relevance = None
        session.commit()
        seed(session, channels=1, confirmed=True)
        assert notifications.dispatch_notifications(session, tenant_id, drain=True) == 1
        assert sender.call_count == 1


def test_success_survives_later_match_failure(database, sender, monkeypatch):
    deliver = notifications._deliver_match
    with Session(database) as session:
        _, matches = seed(session, count=2, channels=1, confirmed=True)
        first_id, second_id = [m.id for m in matches]
        def second_fails(session, match, token):
            if match.id == second_id:
                raise RuntimeError("database failure")
            return deliver(session, match, token)
        monkeypatch.setattr(notifications, "_deliver_match", second_fails)
        with pytest.raises(RuntimeError, match="database failure"):
            notifications.dispatch_notifications(session, drain=True)
    with Session(database) as session:
        assert session.get(TenderMatch, first_id).status == "processed"
        assert session.scalar(select(NotificationLog).where(NotificationLog.match_id == first_id)).status == "sent"


def test_concurrent_notification_workers_do_not_duplicate(postgres_schema, sender):
    Base.metadata.create_all(postgres_schema)
    with Session(postgres_schema) as session:
        seed(session, channels=1, confirmed=True)
    entered, release = Event(), Event()
    def hold(*args):
        entered.set()
        assert release.wait(timeout=10)
    sender.side_effect = hold
    def dispatch():
        with Session(postgres_schema) as session:
            return notifications.dispatch_notifications(session, drain=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(dispatch)
        try:
            assert entered.wait(timeout=10)
            assert pool.submit(dispatch).result(timeout=5) == 0
        finally:
            release.set()
        assert first.result(timeout=5) == 1
    assert sender.call_count == 1


def test_telegram_requires_confirmed_success(monkeypatch):
    response = httpx.Response(200, json={"ok": False}, request=httpx.Request("POST", "https://example.org"))
    monkeypatch.setattr(notifications.httpx, "post", lambda *a, **kw: response)
    with pytest.raises(RuntimeError, match="did not confirm"):
        notifications.send_telegram_message("test-token", "1", "test")


def test_retry_migration_preserves_existing_logs(postgres_schema, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", postgres_schema.url.render_as_string(hide_password=False))
    config = Config("alembic.ini")
    command.upgrade(config, "7f6e8d9c0b1a")
    with Session(postgres_schema) as session:
        _, matches = seed(session, channels=1, confirmed=True)
        channel_id = session.scalar(select(NotificationChannel.id))
        session.execute(text("INSERT INTO notification_logs (match_id, channel_id, status, error_message) VALUES (:m, :c, 'error', 'old failure')"), {"m": matches[0].id, "c": channel_id})
        session.commit()
    command.upgrade(config, "head")
    with Session(postgres_schema) as session:
        log = session.scalar(select(NotificationLog))
        assert log.status == "error" and log.error_message == "old failure"
        assert log.attempt_count == 0 and log.next_attempt_at is None
    command.downgrade(config, "7f6e8d9c0b1a")
    command.upgrade(config, "head")
