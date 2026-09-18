from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from worker import tasks
from worker.ingest import ResultsCheckBatch
from worker.results_progress import read_results_progress, results_check_due, RESULTS_PROGRESS_KEY


class RedisMemory:
    def __init__(self):
        self.values = {}
        self.fail_next_write = False

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, **kwargs):
        if self.fail_next_write:
            self.fail_next_write = False
            raise ConnectionError('Redis write failed')
        assert not kwargs, 'progress must not expire'
        self.values[key] = value


@pytest.fixture
def progress_job(monkeypatch):
    redis = RedisMemory()
    session = MagicMock()
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = session
    monkeypatch.setattr(tasks, 'SessionLocal', session_factory)
    monkeypatch.setattr(tasks, 'get_redis', lambda: redis)
    monkeypatch.setattr(tasks, 'RESULTS_JOB_BATCH_SIZE', 5)
    maximum = MagicMock(return_value=12)
    monkeypatch.setattr(tasks, 'get_pending_results_max_id', maximum)
    monkeypatch.setattr(tasks.time, 'time', lambda: 10_000)
    return redis, session, maximum


def test_chunks_resume_after_no_result_rows_and_restart_snapshot(progress_job, monkeypatch):
    redis, session, maximum = progress_job
    check = MagicMock(side_effect=[ResultsCheckBatch(5, 5), ResultsCheckBatch(5, 10), ResultsCheckBatch(2, 12)])
    monkeypatch.setattr(tasks, 'check_results_for_active_tenders', check)
    # Each invocation models a new RQ job/process; all progress is in Redis.
    tasks.run_results_check_task_job()
    assert check.call_count == 1
    assert read_results_progress(redis)['after_id'] == 5
    tasks.run_results_check_task_job()
    assert read_results_progress(redis)['after_id'] == 10
    tasks.run_results_check_task_job()
    assert read_results_progress(redis) == {'after_id': 0, 'through_id': None, 'next_scan_at': 13_600}
    assert [call.kwargs['after_id'] for call in check.call_args_list] == [0, 5, 10]
    assert all(call.kwargs['through_id'] == 12 and call.kwargs['limit'] == 5 for call in check.call_args_list)
    maximum.assert_called_once()
    assert not results_check_due(redis, 13_599)
    tasks.run_results_check_task_job()
    assert check.call_count == 3
    monkeypatch.setattr(tasks.time, 'time', lambda: 13_600)
    check.side_effect = [ResultsCheckBatch(0, None)]
    tasks.run_results_check_task_job()
    assert maximum.call_count == 2
    assert read_results_progress(redis)['next_scan_at'] == 17_200


def test_failed_database_commit_keeps_cursor(progress_job, monkeypatch):
    redis, session, _ = progress_job
    check = MagicMock(return_value=ResultsCheckBatch(5, 5))
    monkeypatch.setattr(tasks, 'check_results_for_active_tenders', check)
    session.commit.side_effect = RuntimeError('DB commit failed')
    with pytest.raises(RuntimeError, match='DB commit'):
        tasks.run_results_check_task_job()
    assert read_results_progress(redis)['after_id'] == 0
    session.commit.side_effect = None
    tasks.run_results_check_task_job()
    assert [call.kwargs['after_id'] for call in check.call_args_list] == [0, 0]
    assert read_results_progress(redis)['after_id'] == 5


def test_redis_failure_after_commit_repeats_safely(progress_job, monkeypatch):
    redis, session, _ = progress_job
    check = MagicMock(return_value=ResultsCheckBatch(5, 5))
    monkeypatch.setattr(tasks, 'check_results_for_active_tenders', check)
    session.commit.side_effect = lambda: setattr(redis, 'fail_next_write', True)
    with pytest.raises(ConnectionError):
        tasks.run_results_check_task_job()
    assert read_results_progress(redis)['after_id'] == 0
    session.commit.side_effect = None
    tasks.run_results_check_task_job()
    assert [call.kwargs['after_id'] for call in check.call_args_list] == [0, 0]
    assert read_results_progress(redis)['after_id'] == 5


def test_scheduler_queues_fresh_work_before_maintenance(monkeypatch):
    from worker import scheduler
    import belzakupki_db.session as db_session
    redis = RedisMemory()
    session_factory = MagicMock()
    profile = SimpleNamespace(id=7, schedule_interval='1h', last_run_at=None)
    session_factory.return_value.__enter__.return_value.query.return_value.filter.return_value.order_by.return_value.yield_per.return_value = [profile]
    monkeypatch.setattr(db_session, 'SessionLocal', session_factory)
    monkeypatch.setattr(scheduler, 'Queue', MagicMock())
    enqueue = MagicMock(return_value=True)
    monkeypatch.setattr(scheduler, 'enqueue_scheduled_job', enqueue)
    monkeypatch.setattr(scheduler.time, 'time', lambda: 10_000)
    monkeypatch.setattr(redis, 'set', lambda key, value, **kwargs: redis.values.update({key: value}))
    monkeypatch.setattr(scheduler.time, 'sleep', MagicMock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        scheduler.run_scheduler(redis=redis)
    assert [call.kwargs['key'] for call in enqueue.call_args_list] == ['global-ingest', 'profile-7', 'results-check']


def test_corrupt_progress_fails_closed():
    redis = RedisMemory()
    redis.values[RESULTS_PROGRESS_KEY] = '{"after_id": -1, "through_id": 4, "next_scan_at": 0}'
    with pytest.raises(ValueError):
        read_results_progress(redis)
