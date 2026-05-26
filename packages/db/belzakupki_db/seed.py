from __future__ import annotations

from sqlalchemy.orm import Session

from belzakupki_db.models import NotificationChannel, SearchProfile, TenderSource, Tenant, User
from belzakupki_db.auth_utils import hash_password


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
            name="goszakupki.by",
            base_url="https://goszakupki.by",
        )
        session.add(source)
    else:
        source.name = "goszakupki.by"

    icetrade_source = session.query(TenderSource).filter_by(code="icetrade_by").one_or_none()
    if icetrade_source is None:
        icetrade_source = TenderSource(
            code="icetrade_by",
            name="icetrade.by",
            base_url="https://icetrade.by",
        )
        session.add(icetrade_source)
    else:
        icetrade_source.name = "icetrade.by"

    gias_source = session.query(TenderSource).filter_by(code="gias_by").one_or_none()
    if gias_source is None:
        gias_source = TenderSource(
            code="gias_by",
            name="gias.by",
            base_url="https://gias.by",
        )
        session.add(gias_source)
    else:
        gias_source.name = "gias.by"

    butb_source = session.query(TenderSource).filter_by(code="butb_by").one_or_none()
    if butb_source is None:
        butb_source = TenderSource(
            code="butb_by",
            name="butb.by",
            base_url="https://zakupki.butb.by",
        )
        session.add(butb_source)
    else:
        butb_source.name = "butb.by"


def seed_search_profiles(session: Session, tenant_id: int | None = None) -> None:
    # 1. HVAC
    hvac_profile = session.query(SearchProfile).filter_by(name=HVAC_PROFILE_NAME).one_or_none()
    hvac_categories = ["189", "43.22.12.190", "43.22.12.290", "28.25.12.200", "28.25.12.400", "28.25.20.000", "28.99.39.800"]
    if hvac_profile is None:
        hvac_profile = SearchProfile(
            tenant_id=tenant_id,
            name=HVAC_PROFILE_NAME,
            description="Закупки по кондиционерам, вентиляции и климатическому оборудованию.",
            preset_code="hvac",
            keywords=HVAC_KEYWORDS,
            negative_keywords=HVAC_NEGATIVE_KEYWORDS,
            regions=["2"],
            categories=hvac_categories,
            min_score=20.0,
            is_active=True,
        )
        session.add(hvac_profile)
    else:
        hvac_profile.tenant_id = tenant_id
        hvac_profile.preset_code = "hvac"
        hvac_profile.keywords = HVAC_KEYWORDS
        hvac_profile.negative_keywords = HVAC_NEGATIVE_KEYWORDS
        hvac_profile.regions = ["2"]
        hvac_profile.categories = hvac_categories
        hvac_profile.min_score = 20.0
        hvac_profile.is_active = True

    # 2. IT Equipment
    from belzakupki_db.presets import PRESETS
    it_profile = session.query(SearchProfile).filter_by(name="IT-Оборудование и оргтехника").one_or_none()
    it_preset = PRESETS["it_equipment"]
    if it_profile is None:
        it_profile = SearchProfile(
            tenant_id=tenant_id,
            name="IT-Оборудование и оргтехника",
            description="Поставка персональных компьютеров, серверов, оргтехники и картриджей.",
            preset_code="it_equipment",
            keywords=it_preset["default_keywords"],
            negative_keywords=it_preset["default_negative_keywords"],
            regions=["2"],
            categories=["26.20.1", "26.20.2", "26.20.4"],
            min_score=20.0,
            is_active=True,
        )
        session.add(it_profile)
    else:
        it_profile.tenant_id = tenant_id
        it_profile.preset_code = "it_equipment"
        it_profile.keywords = it_preset["default_keywords"]
        it_profile.negative_keywords = it_preset["default_negative_keywords"]

    # 3. Construction SMR
    const_profile = session.query(SearchProfile).filter_by(name="Строительно-монтажные работы (СМР)").one_or_none()
    const_preset = PRESETS["construction_works"]
    if const_profile is None:
        const_profile = SearchProfile(
            tenant_id=tenant_id,
            name="Строительно-монтажные работы (СМР)",
            description="Капитальный ремонт, текущий ремонт, отделочные и кровельные работы.",
            preset_code="construction_works",
            keywords=const_preset["default_keywords"],
            negative_keywords=const_preset["default_negative_keywords"],
            regions=["2"],
            categories=["41.2", "43.3", "43.9"],
            min_score=20.0,
            is_active=True,
        )
        session.add(const_profile)
    else:
        const_profile.tenant_id = tenant_id
        const_profile.preset_code = "construction_works"
        const_profile.keywords = const_preset["default_keywords"]
        const_profile.negative_keywords = const_preset["default_negative_keywords"]

    # 4. Cleaning
    clean_profile = session.query(SearchProfile).filter_by(name="Клининговые услуги").one_or_none()
    clean_preset = PRESETS["cleaning_services"]
    if clean_profile is None:
        clean_profile = SearchProfile(
            tenant_id=tenant_id,
            name="Клининговые услуги",
            description="Услуги профессиональной уборки помещений и территорий.",
            preset_code="cleaning_services",
            keywords=clean_preset["default_keywords"],
            negative_keywords=clean_preset["default_negative_keywords"],
            regions=["2"],
            categories=["81.21.10.000", "81.22.12.000"],
            min_score=20.0,
            is_active=True,
        )
        session.add(clean_profile)
    else:
        clean_profile.tenant_id = tenant_id
        clean_profile.preset_code = "cleaning_services"
        clean_profile.keywords = clean_preset["default_keywords"]
        clean_profile.negative_keywords = clean_preset["default_negative_keywords"]


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


def seed_tenants_and_users(session: Session) -> Tenant:
    tenant = session.query(Tenant).filter_by(name="ООО Ромашка").one_or_none()
    if tenant is None:
        tenant = Tenant(name="ООО Ромашка")
        session.add(tenant)
        session.flush()

    user = session.query(User).filter_by(email="admin@belzakupki.by").one_or_none()
    if user is None:
        user = User(
            tenant_id=tenant.id,
            email="admin@belzakupki.by",
            hashed_password=hash_password("adminpass"),
            full_name="Администратор",
            role="admin"
        )
        session.add(user)
        session.flush()
    return tenant


def seed_database(session: Session) -> None:
    seed_tender_sources(session)
    tenant = seed_tenants_and_users(session)
    seed_search_profiles(session, tenant_id=tenant.id)
    seed_notification_channels(session)
    session.commit()
