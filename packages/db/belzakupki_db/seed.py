from __future__ import annotations

from sqlalchemy.orm import Session

from belzakupki_db.models import NotificationChannel, SearchProfile, TenderSource


HVAC_PROFILE_NAME = "Кондиционеры / HVAC"

HVAC_KEYWORDS = [
    "кондиционер",
    "кондиционеры",
    "сплит-система",
    "сплит система",
    "мультисплит",
    "мульти-сплит",
    "vrf",
    "vrv",
    "вентиляция",
    "климатическое оборудование",
    "монтаж кондиционеров",
    "обслуживание кондиционеров",
    "ремонт кондиционера",
]

HVAC_NEGATIVE_KEYWORDS = [
    "автомобильный кондиционер",
    "авто кондиционер",
    "кондиционер автомобиля",
]


def seed_tender_sources(session: Session) -> None:
    source = session.query(TenderSource).filter_by(code="goszakupki_by").one_or_none()

    if source is None:
        source = TenderSource(
            code="goszakupki_by",
            name="Госзакупки Беларуси",
            base_url="https://goszakupki.by",
        )
        session.add(source)

    icetrade_source = session.query(TenderSource).filter_by(code="icetrade_by").one_or_none()
    if icetrade_source is None:
        icetrade_source = TenderSource(
            code="icetrade_by",
            name="ИС Тендеры (icetrade.by)",
            base_url="https://icetrade.by",
        )
        session.add(icetrade_source)


def seed_search_profiles(session: Session) -> None:
    profile = session.query(SearchProfile).filter_by(name=HVAC_PROFILE_NAME).one_or_none()

    if profile is None:
        profile = SearchProfile(
            name=HVAC_PROFILE_NAME,
            description="Закупки по кондиционерам, вентиляции и климатическому оборудованию.",
            keywords=HVAC_KEYWORDS,
            negative_keywords=HVAC_NEGATIVE_KEYWORDS,
            is_active=True,
        )
        session.add(profile)
        return

    profile.keywords = HVAC_KEYWORDS
    profile.negative_keywords = HVAC_NEGATIVE_KEYWORDS
    profile.is_active = True


def seed_notification_channels(session: Session) -> None:
    import os
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or bot_token == "your-bot-token" or not chat_id or chat_id == "your-chat-id":
        return

    profile = session.query(SearchProfile).filter_by(name=HVAC_PROFILE_NAME).one_or_none()
    if profile is None:
        return

    channel = session.query(NotificationChannel).filter_by(
        profile_id=profile.id,
        type="telegram",
    ).first()

    if channel is None:
        channel = NotificationChannel(
            profile_id=profile.id,
            type="telegram",
            name="Telegram Default",
            config={"chat_id": chat_id},
            is_active=True,
        )
        session.add(channel)
    else:
        channel.config = {"chat_id": chat_id}


def seed_database(session: Session) -> None:
    seed_tender_sources(session)
    seed_search_profiles(session)
    seed_notification_channels(session)
    session.commit()
