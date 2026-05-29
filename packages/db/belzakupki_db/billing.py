from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any
from sqlalchemy import select
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
    now = datetime.now(timezone.utc)
    started_at = tenant.billing_cycle_started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
        
    if now - started_at >= timedelta(days=30):
        tenant.ai_credits_used = 0
        tenant.billing_cycle_started_at = now
        session.add(tenant)
        session.flush()


def can_use_ai_credits(session: Session, tenant_id: int) -> bool:
    """Проверяет, доступен ли лимит ИИ-анализа для данной организации.

    Также сбрасывает лимиты при переходе на новый расчетный месяц подписки
    и переводит на бесплатный тариф, если платная подписка закончилась.
    """
    tenant = session.get(Tenant, tenant_id)
    if not tenant or not tenant.is_active:
        return False
        
    # Проверка срока действия подписки (для free нет срока действия)
    if tenant.plan != "free" and tenant.subscription_expires_at:
        expires_at = tenant.subscription_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
            
        if datetime.now(timezone.utc) > expires_at:
            # Срок подписки истек, возвращаем на free
            tenant.plan = "free"
            tenant.subscription_expires_at = None
            session.add(tenant)
            session.flush()

    check_and_reset_billing_cycle(session, tenant)
    
    limits = PLAN_LIMITS.get(tenant.plan, PLAN_LIMITS["free"])
    return tenant.ai_credits_used < limits["max_ai_credits"]


def increment_ai_credits(session: Session, tenant_id: int) -> None:
    """Увеличивает счетчик использованных ИИ-анализов на 1."""
    tenant = session.get(Tenant, tenant_id)
    if tenant:
        tenant.ai_credits_used += 1
        session.add(tenant)
        session.flush()
