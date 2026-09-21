"""Testy kalendarza planu lekcji Librus APIX."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.util import dt as dt_util

from custom_components.librus_apix.calendar import (
    LibrusPlanLekcjiCalendar,
    _lesson_to_event,
)


def _lekcja(
    numer=1,
    przedmiot="Matematyka",
    data="2026-09-21",
    od="08:00",
    do="08:45",
    nauczyciel_sala="12",
    zastepstwo=False,
    odwolana=False,
    info="",
):
    return {
        "data": data,
        "dzien_tygodnia": "Poniedziałek",
        "numer": numer,
        "przedmiot": przedmiot,
        "nauczyciel_sala": nauczyciel_sala,
        "od": od,
        "do": do,
        "odwolana": odwolana,
        "zastepstwo": zastepstwo,
        "info": info,
        "szczegoly": {},
    }


def _calendar(plan):
    coordinator = MagicMock()
    coordinator.data = {
        "student_info": SimpleNamespace(name="Jan Kowalski"),
        "plan_lekcji": plan,
    }
    entry = MagicMock()
    entry.entry_id = "test-entry"
    return LibrusPlanLekcjiCalendar(coordinator, entry)


def test_lesson_to_event_mapuje_pola():
    """Lekcja staje sie godzinowym CalendarEvent w lokalnej strefie HA."""
    event = _lesson_to_event(
        _lekcja(
            numer=3,
            przedmiot="Fizyka",
            nauczyciel_sala="Anna Nowak - 24",
        )
    )

    assert event is not None
    assert event.summary == "Fizyka"
    assert event.location == "Anna Nowak - 24"
    assert event.description == "Lekcja 3"
    assert event.start.tzinfo == dt_util.get_default_time_zone()
    assert event.end.tzinfo == dt_util.get_default_time_zone()
    assert event.start.hour == 8
    assert event.end.hour == 8
    assert event.end.minute == 45


def test_lesson_to_event_oznacza_zastepstwo_i_odwolanie():
    """Zmiany planu sa widoczne bez utraty samego wydarzenia."""
    replacement = _lesson_to_event(
        _lekcja(zastepstwo=True, info="Zastępstwo")
    )
    cancelled = _lesson_to_event(
        _lekcja(odwolana=True, info="Lekcja odwołana")
    )

    assert replacement.summary == "[ZASTĘPSTWO] Matematyka"
    assert "Zastępstwo" in replacement.description
    assert cancelled.summary == "[ODWOŁANA] Matematyka"
    assert "Lekcja odwołana" in cancelled.description


def test_lesson_to_event_pomija_bledne_godziny():
    """Niepoprawna lekcja nie moze zepsuc calego kalendarza."""
    assert _lesson_to_event(_lekcja(od="", do="")) is None
    assert _lesson_to_event(_lekcja(od="10:00", do="09:00")) is None


async def test_async_get_events_filtruje_zadany_zakres():
    """Calendar zwraca tylko lekcje przecinajace zakres podany przez HA."""
    tz = dt_util.get_default_time_zone()
    calendar = _calendar(
        [
            _lekcja(przedmiot="Matematyka", od="08:00", do="08:45"),
            _lekcja(numer=2, przedmiot="Fizyka", od="09:00", do="09:45"),
            _lekcja(
                numer=1,
                przedmiot="Historia",
                data="2026-09-22",
                od="08:00",
                do="08:45",
            ),
        ]
    )

    events = await calendar.async_get_events(
        MagicMock(),
        datetime(2026, 9, 21, 8, 30, tzinfo=tz),
        datetime(2026, 9, 21, 9, 15, tzinfo=tz),
    )

    assert [event.summary for event in events] == ["Matematyka", "Fizyka"]


def test_event_pomija_odwolana_lekcje_jako_najblizsza():
    """Odwolana lekcja zostaje w widoku kalendarza, ale nie jest next event."""
    now = dt_util.now()
    today = now.date().strftime("%Y-%m-%d")
    start1 = (now + timedelta(minutes=30)).strftime("%H:%M")
    end1 = (now + timedelta(minutes=60)).strftime("%H:%M")
    start2 = (now + timedelta(minutes=90)).strftime("%H:%M")
    end2 = (now + timedelta(minutes=120)).strftime("%H:%M")

    calendar = _calendar(
        [
            _lekcja(
                przedmiot="Matematyka",
                data=today,
                od=start1,
                do=end1,
                odwolana=True,
            ),
            _lekcja(
                numer=2,
                przedmiot="Fizyka",
                data=today,
                od=start2,
                do=end2,
            ),
        ]
    )

    assert calendar.event is not None
    assert calendar.event.summary == "Fizyka"
