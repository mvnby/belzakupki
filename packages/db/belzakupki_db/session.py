"""Управление сессиями базы данных SQLAlchemy.

Настраивает движок подключения (engine) и фабрику сессий (SessionLocal).
Предоставляет генератор для автоматического управления транзакциями.
"""
from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://belzakupki:belzakupki@localhost:5432/belzakupki",
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_session() -> Generator[Session, None, None]:
    """Генератор контекста сессии базы данных для использования в FastAPI (Depends) или CLI.

    Автоматически делает rollback при возникновении любого исключения и гарантирует
    закрытие соединения (close) в блоке finally.
    """
    session = SessionLocal()

    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
