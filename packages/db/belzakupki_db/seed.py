from __future__ import annotations

from sqlalchemy.orm import Session

from belzakupki_db.models import SearchProfile, TenderSource


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


def seed_database(session: Session) -> None:
    seed_tender_sources(session)
    seed_search_profiles(session)
    session.commit()
