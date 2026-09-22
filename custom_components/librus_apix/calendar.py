"""Platforma kalendarza planu lekcji dla integracji Librus APIX."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import (
    SOURCE_TIMETABLE,
    LibrusConfigEntry,
    LibrusDataUpdateCoordinator,
)
from .entity import LibrusEntity

PARALLEL_UPDATES = 0


def _parse_local_datetime(date_str: str, time_str: str) -> Optional[datetime]:
    """Polacz date i godzine z Librusa i ustaw lokalna strefe HA."""
    if not date_str or not time_str:
        return None

    try:
        value = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None

    return value.replace(tzinfo=dt_util.get_default_time_zone())


def _lesson_summary(lesson: Dict[str, Any]) -> str:
    """Zbuduj tytul wydarzenia kalendarza."""
    subject = lesson.get("przedmiot", "") or "Lekcja"
    if lesson.get("odwolana"):
        return f"[ODWOŁANA] {subject}"
    if lesson.get("zastepstwo"):
        return f"[ZASTĘPSTWO] {subject}"
    return subject


def _lesson_description(lesson: Dict[str, Any]) -> Optional[str]:
    """Build a useful calendar description from timetable data only."""
    parts: List[str] = []

    number = lesson.get("numer")
    if number is not None:
        parts.append(f"Lekcja {number}")

    info = (lesson.get("info") or "").strip()
    if info:
        parts.append(info)

    details = lesson.get("szczegoly") or {}
    for _change_name, change_details in details.items():
        if not isinstance(change_details, dict):
            continue
        for key, label in (
            ("teacher_swap", "Nauczyciel"),
            ("subject_swap", "Przedmiot"),
            ("classroom_swap", "Sala"),
            ("date_added", "Dodano"),
        ):
            value = change_details.get(key)
            if value:
                parts.append(f"{label}: {value}")

    return "\n".join(dict.fromkeys(parts)) or None


def _lesson_to_event(lesson: Dict[str, Any]) -> Optional[CalendarEvent]:
    """Zamien lekcje na wydarzenie Home Assistant Calendar."""
    start = _parse_local_datetime(lesson.get("data", ""), lesson.get("od", ""))
    end = _parse_local_datetime(lesson.get("data", ""), lesson.get("do", ""))

    if start is None or end is None or end < start:
        return None

    return CalendarEvent(
        start=start,
        end=end,
        summary=_lesson_summary(lesson),
        description=_lesson_description(lesson),
        location=(lesson.get("nauczyciel_sala") or "").strip() or None,
        uid=f'{lesson.get("data", "")}-{lesson.get("numer", "")}',
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: LibrusConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Skonfiguruj kalendarz planu lekcji."""
    coordinator = config_entry.runtime_data
    async_add_entities([LibrusPlanLekcjiCalendar(coordinator, config_entry)])


class LibrusPlanLekcjiCalendar(LibrusEntity, CalendarEntity):
    """Kalendarz planu lekcji z danych pobranych przez wspolny coordinator."""

    _required_sources = frozenset({SOURCE_TIMETABLE})
    _availability_key = "timetable"

    def __init__(
        self,
        coordinator: LibrusDataUpdateCoordinator,
        config_entry: LibrusConfigEntry,
    ) -> None:
        super().__init__(coordinator, config_entry)
        self._attr_translation_key = "lesson_timetable"
        self._attr_unique_id = f"{config_entry.entry_id}_plan_lekcji_calendar"

    def _events(self) -> List[CalendarEvent]:
        """Zwroc wszystkie poprawne wydarzenia z aktualnego cache planu."""
        result: List[CalendarEvent] = []
        for lesson in (self.coordinator.data or {}).get("plan_lekcji", []):
            event = _lesson_to_event(lesson)
            if event is not None:
                result.append(event)
        return sorted(result, key=lambda event: event.start)

    @property
    def event(self) -> Optional[CalendarEvent]:
        """Zwroc trwajaca lub najblizsza nieodwolana lekcje."""
        now = dt_util.now()
        lessons = (self.coordinator.data or {}).get("plan_lekcji", [])

        events: List[tuple[CalendarEvent, Dict[str, Any]]] = []
        for lesson in lessons:
            event = _lesson_to_event(lesson)
            if event is not None:
                events.append((event, lesson))

        events.sort(key=lambda item: item[0].start)
        for event, lesson in events:
            if lesson.get("odwolana"):
                continue
            if event.end > now:
                return event
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> List[CalendarEvent]:
        """Zwroc wydarzenia zachodzace na podany zakres czasu."""
        return [
            event
            for event in self._events()
            if event.end > start_date and event.start < end_date
        ]
