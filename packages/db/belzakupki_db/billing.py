from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from belzakupki_db.models import Tenant

PLAN_LIMITS = {
    "free": {
        "max_active_profiles": 1,
        "max_ai_credits": 0,
        "max_channels_per_profile": 1,
    },
    "starter": {
        "max_active_profiles": 2,
        "max_ai_credits": 30,
        "max_channels_per_profile": 1,
    },
    "professional": {
        "max_active_profiles": 10,
        "max_ai_credits": 200,
        "max_channels_per_profile": 3,
    },
    "enterprise": {
        "max_active_profiles": 9999,
        "max_ai_credits": 99999,
        "max_channels_per_profile": 99,
    },
}


def check_and_reset_billing_cycle(session: Session, tenant: Tenant) -> None:
    """Проверяет дату начала текущего платежного цикла.

    Если прошло более 30 дней, сбрасывает счетчик лимитов ИИ и обновляет дату старта цикла.
    """
    session.flush()
    _reset_cycle(session, tenant.id, datetime.now(timezone.utc))
    session.refresh(tenant)


def _reset_cycle(session: Session, tenant_id: int, now: datetime) -> None:
    # Recheck the date in the UPDATE itself: a stale ORM object must never
    # reset credits that another transaction has already used in a new cycle.
    session.execute(
        update(Tenant)
        .where(Tenant.id == tenant_id,
               Tenant.billing_cycle_started_at <= now - timedelta(days=30))
        .values(ai_credits_used=0, billing_cycle_started_at=now)
        .execution_options(synchronize_session=False)
    )


def _prepare_billing(session: Session, tenant_id: int) -> None:
    session.flush()
    now = datetime.now(timezone.utc)
    session.execute(
        update(Tenant)
        .where(Tenant.id == tenant_id, Tenant.plan != "free",
               Tenant.subscription_expires_at <= now)
        .values(plan="free", subscription_expires_at=None)
        .execution_options(synchronize_session=False)
    )
    _reset_cycle(session, tenant_id, now)


def _credit_available():
    limit = case(
        *((Tenant.plan == plan, limits["max_ai_credits"])
          for plan, limits in PLAN_LIMITS.items()),
        else_=0,
    )
    return Tenant.is_active.is_(True) & (Tenant.ai_credits_used < limit)


def can_use_ai_credits(session: Session, tenant_id: int) -> bool:
    """Проверяет, доступен ли лимит ИИ-анализа для данной организации.

    Также сбрасывает лимиты при переходе на новый расчетный месяц подписки
    и переводит на бесплатный тариф, если платная подписка закончилась.
    """
    _prepare_billing(session, tenant_id)
    return session.scalar(select(Tenant.id).where(
        Tenant.id == tenant_id, _credit_available(),
    )) is not None


def increment_ai_credits(session: Session, tenant_id: int) -> None:
    """Увеличивает счетчик использованных ИИ-анализов на 1."""
    session.execute(update(Tenant).where(Tenant.id == tenant_id).values(
        ai_credits_used=Tenant.ai_credits_used + 1,
    ))


@dataclass
class AICreditReservation:
    available: bool
    consumed: bool = False


@contextmanager
def reserve_ai_credit(session: Session, tenant_id: int | None):
    """Reserve one completed match analysis, including both AI stages.

    The conditional UPDATE serializes competing reservations in PostgreSQL.
    The reservation and match result belong to the caller's transaction. A
    failed analysis rolls back its savepoint; a missing result refunds the
    reservation. Tenant-less legacy profiles keep their existing behavior.
    """
    with session.begin_nested():
        available = True
        if tenant_id is not None:
            _prepare_billing(session, tenant_id)
            tenant = session.scalars(
                update(Tenant)
                .where(Tenant.id == tenant_id, _credit_available())
                .values(ai_credits_used=Tenant.ai_credits_used + 1)
                .returning(Tenant)
                .execution_options(populate_existing=True)
            ).one_or_none()
            available = tenant is not None
        reservation = AICreditReservation(available)
        yield reservation
        if tenant_id is not None and available and not reservation.consumed:
            session.execute(update(Tenant).where(Tenant.id == tenant_id).values(
                ai_credits_used=Tenant.ai_credits_used - 1,
            ))
