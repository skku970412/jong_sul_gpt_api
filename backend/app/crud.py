from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .models import ChargingSession, Reservation, ReservationSlot, ReservationStatus
from .time_utils import (
    UTC,
    business_day_bounds_utc,
    business_timezone,
    ensure_utc,
)

SLOT_INTERVAL_MINUTES = 30
OVERLAP_ERROR_MESSAGE = "해당 시간대 이미 예약이 존재합니다."


def _lock_session(session: Session, *, session_id: int) -> None:
    """
    Acquire a row-level lock for the target charging session so that concurrent
    reservations on the same session serialize properly.
    """
    stmt = (
        select(ChargingSession.id)
        .where(ChargingSession.id == session_id)
        .with_for_update()
    )
    session.scalars(stmt).first()


def normalize_plate(plate: str) -> str:
    return "".join(plate.split()).upper()


def ensure_base_sessions(session: Session, *, names: Iterable[str]) -> None:
    names_tuple = tuple(names)
    existing_count = session.scalar(select(func.count()).select_from(ChargingSession))
    if existing_count and existing_count >= len(names_tuple):
        return

    for idx, name in enumerate(names_tuple, start=1):
        if session.get(ChargingSession, idx) is None:
            session.add(ChargingSession(id=idx, name=name))
    session.commit()


def list_sessions(session: Session) -> list[ChargingSession]:
    return session.scalars(select(ChargingSession).order_by(ChargingSession.id)).all()


def reservations_by_date(session: Session, *, date_value: date) -> list[Reservation]:
    start, end = business_day_bounds_utc(date_value)
    stmt = (
        select(Reservation)
        .where(and_(Reservation.start_time >= start, Reservation.start_time < end))
        .order_by(Reservation.start_time)
    )
    return session.scalars(stmt).all()


def reservations_by_session_and_date(
    session: Session, *, session_id: int, date_value: date
) -> list[Reservation]:
    start, end = business_day_bounds_utc(date_value)
    stmt = (
        select(Reservation)
        .where(
            and_(
                Reservation.session_id == session_id,
                Reservation.start_time >= start,
                Reservation.start_time < end,
            )
        )
        .order_by(Reservation.start_time)
    )
    return session.scalars(stmt).all()


def create_reservation(
    session: Session,
    *,
    session_id: int,
    plate: str,
    start_time: datetime,
    end_time: datetime,
    contact_email: str | None = None,
) -> Reservation:
    # Prevent concurrent reservation creation on the same session.
    _lock_session(session, session_id=session_id)

    start_time_utc = ensure_utc(start_time)
    end_time_utc = ensure_utc(end_time)
    if start_time_utc is None or end_time_utc is None:
        raise ValueError("예약 시간 정보가 올바르지 않습니다.")
    if end_time_utc <= start_time_utc:
        raise ValueError("종료 시간이 시작 시간 이후여야 합니다.")

    normalized_plate = normalize_plate(plate)
    ensure_no_overlap(session, session_id=session_id, start=start_time_utc, end=end_time_utc)
    ensure_no_conflict_for_plate(
        session, plate=normalized_plate, start=start_time_utc, end=end_time_utc
    )

    slot_starts = _generate_slot_starts(start_time_utc, end_time_utc)
    if not slot_starts:
        raise ValueError("Reservation duration must cover at least one slot.")

    reservation = Reservation(
        session_id=session_id,
        plate=plate.strip(),
        plate_normalized=normalized_plate,
        start_time=start_time_utc,
        end_time=end_time_utc,
        status=ReservationStatus.CONFIRMED,
        contact_email=(contact_email.strip().lower() if contact_email else None),
    )
    reservation.slots = [
        ReservationSlot(session_id=session_id, slot_start=slot_start) for slot_start in slot_starts
    ]
    session.add(reservation)
    try:
        session.flush()
        normalized_start = ensure_utc(reservation.start_time)
        normalized_end = ensure_utc(reservation.end_time)
        if normalized_start is not None:
            reservation.start_time = normalized_start
        if normalized_end is not None:
            reservation.end_time = normalized_end
        for slot in reservation.slots:
            normalized_slot = ensure_utc(slot.slot_start)
            if normalized_slot is not None:
                slot.slot_start = normalized_slot
    except IntegrityError as exc:
        session.rollback()
        raise ValueError(OVERLAP_ERROR_MESSAGE) from exc
    return reservation


def ensure_no_overlap(
    session: Session,
    *,
    session_id: int,
    start: datetime,
    end: datetime,
) -> None:
    start_utc = ensure_utc(start)
    end_utc = ensure_utc(end)
    slot_starts = _generate_slot_starts(start_utc, end_utc)
    if not slot_starts:
        return

    overlap_stmt = (
        select(ReservationSlot.slot_start)
        .where(
            and_(
                ReservationSlot.session_id == session_id,
                ReservationSlot.slot_start.in_(slot_starts),
            )
        )
        .limit(1)
    )
    conflict = session.scalars(overlap_stmt).first()
    if conflict:
        raise ValueError(OVERLAP_ERROR_MESSAGE)

def ensure_no_conflict_for_plate(
    session: Session,
    *,
    plate: str,
    start: datetime,
    end: datetime,
) -> None:
    start_utc = ensure_utc(start)
    end_utc = ensure_utc(end)

    stmt = (
        select(Reservation)
        .where(
            and_(
                Reservation.plate_normalized == plate,
                Reservation.status != ReservationStatus.CANCELLED,
                Reservation.start_time < end_utc,
                Reservation.end_time > start_utc,
            )
        )
        .with_for_update()
    )
    conflict = session.scalars(stmt).first()
    if conflict:
        raise ValueError("해당 차량은 다른 시간대에 이미 예약되어 있습니다.")


def find_conflicting_plate_reservation(
    session: Session,
    *,
    plate: str,
    start: Optional[datetime],
    end: Optional[datetime],
) -> Optional[Reservation]:
    normalized_plate = normalize_plate(plate)
    stmt = select(Reservation).where(Reservation.plate_normalized == normalized_plate)
    if start and end:
        start_utc = ensure_utc(start)
        end_utc = ensure_utc(end)
        stmt = stmt.where(
            and_(
                Reservation.status != ReservationStatus.CANCELLED,
                Reservation.start_time < end_utc,
                Reservation.end_time > start_utc,
            )
        )
    stmt = stmt.order_by(Reservation.start_time.desc())
    return session.scalars(stmt).first()


def find_active_reservation_by_plate(
    session: Session,
    *,
    plate: str,
    when: datetime,
) -> Optional[Reservation]:
    normalized_plate = normalize_plate(plate)
    moment = ensure_utc(when)
    if moment is None:
        return None

    stmt = (
        select(Reservation)
        .where(
            and_(
                Reservation.plate_normalized == normalized_plate,
                Reservation.status != ReservationStatus.CANCELLED,
                Reservation.start_time <= moment,
                Reservation.end_time > moment,
            )
        )
        .order_by(Reservation.start_time.asc())
    )
    return session.scalars(stmt).first()


def delete_reservation(session: Session, reservation_id: str) -> bool:
    reservation = session.get(Reservation, reservation_id)
    if not reservation:
        return False
    session.delete(reservation)
    return True


def reservations_for_user(
    session: Session,
    *,
    email: str | None = None,
    plate: str | None = None,
) -> list[Reservation]:
    if not email and not plate:
        raise ValueError("email 또는 plate 중 하나는 반드시 제공해야 합니다.")

    stmt = select(Reservation).order_by(Reservation.start_time.desc())
    conditions = []
    if email:
        conditions.append(func.lower(Reservation.contact_email) == email.lower())
    if plate:
        conditions.append(Reservation.plate_normalized == normalize_plate(plate))
    if conditions:
        stmt = stmt.where(and_(*conditions))
    return session.scalars(stmt).all()


def delete_reservation_for_user(
    session: Session,
    *,
    reservation_id: str,
    email: str | None = None,
    plate: str | None = None,
) -> bool:
    if not email and not plate:
        raise ValueError("email 또는 plate 중 하나는 반드시 제공해야 합니다.")

    stmt = select(Reservation).where(Reservation.id == reservation_id)
    if email:
        stmt = stmt.where(func.lower(Reservation.contact_email) == email.lower())
    if plate:
        stmt = stmt.where(Reservation.plate_normalized == normalize_plate(plate))

    reservation = session.scalars(stmt).first()
    if reservation is None:
        return False
    session.delete(reservation)
    return True


def migrate_reservation_times_to_utc(session: Session) -> None:
    """Backfill existing reservations and slots to UTC if stored without tzinfo."""
    logger = logging.getLogger(__name__)
    zone = business_timezone()
    reservations = session.scalars(
        select(Reservation).options(selectinload(Reservation.slots))
    ).all()

    updated = False
    for reservation in reservations:
        if reservation.start_time and reservation.start_time.tzinfo is None:
            reservation.start_time = reservation.start_time.replace(tzinfo=zone).astimezone(UTC)
            updated = True
        if reservation.end_time and reservation.end_time.tzinfo is None:
            reservation.end_time = reservation.end_time.replace(tzinfo=zone).astimezone(UTC)
            updated = True
        if reservation.created_at and reservation.created_at.tzinfo is None:
            reservation.created_at = reservation.created_at.replace(tzinfo=zone).astimezone(UTC)
            updated = True
        if reservation.updated_at and reservation.updated_at.tzinfo is None:
            reservation.updated_at = reservation.updated_at.replace(tzinfo=zone).astimezone(UTC)
            updated = True

        for slot in reservation.slots:
            if slot.slot_start and slot.slot_start.tzinfo is None:
                slot.slot_start = slot.slot_start.replace(tzinfo=zone).astimezone(UTC)
                updated = True

    if updated:
        try:
            session.flush()
        except IntegrityError as exc:  # pragma: no cover - defensive
            session.rollback()
            logger.warning(
                "Skipping UTC migration due to unique constraint conflict: %s", exc
            )


def ensure_reservation_slots(session: Session) -> None:
    reservations = session.scalars(
        select(Reservation)
        .where(Reservation.status != ReservationStatus.CANCELLED)
        .options(selectinload(Reservation.slots))
    ).all()

    updated = False
    for reservation in reservations:
        start_utc = ensure_utc(reservation.start_time)
        end_utc = ensure_utc(reservation.end_time)
        if start_utc is None or end_utc is None:
            continue

        if reservation.start_time != start_utc:
            reservation.start_time = start_utc
            updated = True
        if reservation.end_time != end_utc:
            reservation.end_time = end_utc
            updated = True

        slot_starts = _generate_slot_starts(start_utc, end_utc)
        if not slot_starts:
            continue

        existing: set[datetime] = set()
        for slot in reservation.slots:
            normalized_slot = ensure_utc(slot.slot_start)
            if normalized_slot is None:
                continue
            if slot.slot_start != normalized_slot:
                slot.slot_start = normalized_slot
                updated = True
            existing.add(normalized_slot)

        missing = [slot_start for slot_start in slot_starts if slot_start not in existing]
        if not missing:
            continue

        reservation.slots.extend(
            ReservationSlot(session_id=reservation.session_id, slot_start=slot_start)
            for slot_start in missing
        )
        updated = True

    if updated:
        session.flush()


def _generate_slot_starts(start: datetime, end: datetime) -> list[datetime]:
    """Return slot start datetimes between start (inclusive) and end (exclusive)."""
    if start is None or end is None:
        return []

    start_utc = ensure_utc(start)
    end_utc = ensure_utc(end)
    if start_utc is None or end_utc is None or end_utc <= start_utc:
        return []

    slots: list[datetime] = []
    current = start_utc
    delta = timedelta(minutes=SLOT_INTERVAL_MINUTES)
    while current < end_utc:
        slots.append(current)
        current += delta
    return slots
