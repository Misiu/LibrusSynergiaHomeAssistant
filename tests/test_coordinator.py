"""Testy wspolnego coordinatora Librus Synergia."""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from librus_apix.exceptions import AuthorizationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.librus.const import DOMAIN
from custom_components.librus.coordinator import (
    EVENT_NOWA_OCENA,
    EVENT_NOWA_WIADOMOSC,
    EVENT_NOWE_ZADANIE,
    EVENT_NOWE_ZDARZENIE,
    EVENT_ZMIANA_PLANU,
    ALL_SOURCES,
    SOURCE_TIMETABLE,
    LibrusDataUpdateCoordinator,
    _current_semester,
    _jest_nowa,
)


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Librus",
        data={"username": "test", "password": "secret"},
    )


def _client() -> MagicMock:
    client = MagicMock()
    client.async_get_student_information = AsyncMock(
        return_value=SimpleNamespace(name="Jan Kowalski")
    )
    client.async_get_grades = AsyncMock(return_value=[])
    client.async_get_messages = AsyncMock(return_value=[])
    client.async_get_homework = AsyncMock(return_value=[])
    client.async_get_schedule = AsyncMock(return_value=[])
    client.async_get_timetable = AsyncMock(return_value=[])
    return client


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 9, 1), 1),
        (date(2027, 1, 15), 1),
        (date(2027, 2, 1), 2),
        (date(2027, 6, 30), 2),
        (date(2027, 7, 1), 2),
    ],
)
def test_current_semester(
    freezer: FrozenDateTimeFactory, day: date, expected: int
) -> None:
    """Styczen nadal nalezy do pierwszego semestru."""
    freezer.move_to(day)
    assert _current_semester() == expected


async def test_pierwszy_blad_ocen_nie_blokuje_innych_zrodel(
    hass: HomeAssistant,
) -> None:
    """A single unavailable source does not block the whole integration."""
    entry = _entry()
    client = _client()
    client.async_get_grades.return_value = None
    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)

    result = await coordinator._async_update_data()

    assert result["availability"]["grades"] is False
    assert result["oceny"] == []
    assert result["student_info"].name == "Jan Kowalski"


async def test_pusty_cache_ocen_jest_poprawnym_cache(hass: HomeAssistant) -> None:
    """Uczen bez ocen nie traci dostepnosci przy chwilowym bledzie ocen."""
    entry = _entry()
    client = _client()
    client.async_get_grades.return_value = None

    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)
    student = SimpleNamespace(name="Jan Kowalski")
    coordinator.data = {
        "student_info": student,
        "oceny": [],
        "oceny_wg_przedmiotu": {},
        "wiadomosci": [],
        "zadania": [],
        "terminarz": [],
        "plan_lekcji": [],
        "semestr_biezacy": 1,
    }

    result = await coordinator._async_update_data()

    assert result["student_info"].name == student.name
    assert result["oceny"] == []
    assert result["oceny_wg_przedmiotu"] == {}
    assert result["wiadomosci"] == []
    assert result["zadania"] == []
    assert result["terminarz"] == []
    assert result["plan_lekcji"] == []


async def test_czesciowy_blad_zachowuje_cache_innych_endpointow(hass: HomeAssistant) -> None:
    """Awaria pojedynczych endpointow nie zeruje ostatnich poprawnych danych."""
    entry = _entry()
    client = _client()
    client.async_get_messages.return_value = None
    client.async_get_schedule.return_value = None
    client.async_get_timetable.return_value = None

    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)
    cached_message = {
        "author": "Sekretariat",
        "title": "Informacja",
        "date": "20.09.2026",
        "href": "/message/1",
        "unread": True,
        "has_attachment": False,
        "jest_nowa": True,
    }
    cached_schedule = [{"data": "2026-09-22", "tytul": "Sprawdzian", "przedmiot": "Fizyka"}]
    cached_plan = [
        {
            "data": "2026-09-22",
            "numer": 1,
            "przedmiot": "Fizyka",
            "od": "08:00",
            "do": "08:45",
            "zastepstwo": False,
            "odwolana": False,
            "info": "",
        }
    ]
    coordinator.data = {
        "student_info": SimpleNamespace(name="Jan Kowalski"),
        "oceny": [],
        "oceny_wg_przedmiotu": {},
        "wiadomosci": [cached_message],
        "zadania": [],
        "terminarz": cached_schedule,
        "plan_lekcji": cached_plan,
        "semestr_biezacy": 1,
    }

    result = await coordinator._async_update_data()

    assert result["wiadomosci"] == [cached_message]
    assert result["terminarz"] is cached_schedule
    assert result["plan_lekcji"] is cached_plan


async def test_coordinator_jest_powiazany_z_config_entry(hass: HomeAssistant) -> None:
    """HA 2026.9 powinien dostac config_entry jawnie w coordinatorze."""
    entry = _entry()
    coordinator = LibrusDataUpdateCoordinator(hass, entry, _client())

    assert coordinator.config_entry is entry
    assert coordinator.update_interval == timedelta(hours=2)



async def test_auth_rejection_przerywa_dalsze_endpointy(hass: HomeAssistant) -> None:
    """Po bledzie autoryzacji coordinator nie wykonuje kolejnych zapytan."""
    entry = _entry()
    client = _client()
    client.async_get_student_information.return_value = None
    client.last_auth_error = AuthorizationError("bad credentials")

    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()

    client.async_get_grades.assert_not_awaited()
    client.async_get_messages.assert_not_awaited()
    client.async_get_homework.assert_not_awaited()
    client.async_get_schedule.assert_not_awaited()
    client.async_get_timetable.assert_not_awaited()



async def test_pelna_awaria_z_cache_nadal_jest_update_failed(hass: HomeAssistant) -> None:
    """Stary cache nie moze maskowac calkowitej awarii Librusa."""
    entry = _entry()
    client = _client()
    client.async_get_student_information.return_value = None
    client.async_get_grades.return_value = None
    client.async_get_messages.return_value = None
    client.async_get_homework.return_value = None
    client.async_get_schedule.return_value = None
    client.async_get_timetable.return_value = None

    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)
    coordinator.data = {
        "student_info": SimpleNamespace(name="Jan Kowalski"),
        "oceny": [],
        "oceny_wg_przedmiotu": {},
        "wiadomosci": [],
        "zadania": [],
        "terminarz": [],
        "plan_lekcji": [],
        "semestr_biezacy": 1,
    }

    with pytest.raises(UpdateFailed, match="Librus API is unavailable"):
        await coordinator._async_update_data()



async def test_partial_source_availability_logs_only_transitions(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Partial source failures log once and recovery logs once."""
    entry = _entry()
    client = _client()
    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)

    client.async_get_messages.return_value = None
    unsubscribe = coordinator.async_add_listener(
        lambda: None, frozenset(ALL_SOURCES)
    )
    await coordinator._async_update_data()
    await coordinator._async_update_data()

    unavailable_logs = [
        record.message
        for record in caplog.records
        if record.message == "Librus data source messages is unavailable"
    ]
    assert len(unavailable_logs) == 1

    client.async_get_messages.return_value = []
    await coordinator._async_update_data()
    await coordinator._async_update_data()

    recovery_logs = [
        record.message
        for record in caplog.records
        if record.message == "Librus data source messages is available again"
    ]
    unsubscribe()
    assert len(recovery_logs) == 1



async def test_first_recovery_of_source_does_not_emit_old_events(
    hass: HomeAssistant,
) -> None:
    """The first successful fetch of a recovered source only seeds its cache."""
    entry = _entry()
    client = _client()
    client.async_get_messages.return_value = None
    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)
    events = []
    hass.bus.async_listen(EVENT_NOWA_WIADOMOSC, events.append)

    await coordinator._async_update_data()
    unsubscribe = coordinator.async_add_listener(
        lambda: None, frozenset(ALL_SOURCES)
    )

    client.async_get_messages.return_value = [
        {
            "author": "Sekretariat",
            "title": "Existing message",
            "date": "2026-09-20",
            "href": "/message/1",
            "unread": True,
            "has_attachment": False,
        }
    ]
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    assert events == []

    client.async_get_messages.return_value.append(
        {
            "author": "Sekretariat",
            "title": "New message",
            "date": "2026-09-21",
            "href": "/message/2",
            "unread": True,
            "has_attachment": False,
        }
    )
    await coordinator._async_update_data()
    await hass.async_block_till_done()

    unsubscribe()
    assert len(events) == 1
    assert events[0].data["temat"] == "New message"



def test_jest_nowa_handles_empty_and_invalid_dates() -> None:
    """Invalid or empty date strings are not treated as new."""
    assert _jest_nowa("") is False
    assert _jest_nowa("not-a-date") is False


async def test_unexpected_client_error_is_wrapped(hass: HomeAssistant) -> None:
    """Unexpected library errors become coordinator UpdateFailed."""
    entry = _entry()
    client = _client()
    client.async_get_student_information.side_effect = RuntimeError("boom")
    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)

    with pytest.raises(UpdateFailed, match="Blad komunikacji z API: boom"):
        await coordinator._async_update_data()


async def test_new_items_fire_all_supported_events(hass: HomeAssistant) -> None:
    """After seeding, new items from each source emit their HA events."""
    entry = _entry()
    client = _client()
    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)

    await coordinator._async_update_data()
    unsubscribe = coordinator.async_add_listener(
        lambda: None, frozenset(ALL_SOURCES)
    )

    received: dict[str, list] = {
        EVENT_NOWA_WIADOMOSC: [],
        EVENT_NOWA_OCENA: [],
        EVENT_NOWE_ZADANIE: [],
        EVENT_NOWE_ZDARZENIE: [],
        EVENT_ZMIANA_PLANU: [],
    }
    for event_type in received:
        hass.bus.async_listen(
            event_type,
            lambda event, event_type=event_type: received[event_type].append(event),
        )

    client.async_get_messages.return_value = [
        {
            "author": "Sekretariat",
            "title": "Nowa wiadomosc",
            "date": "2026-09-21",
            "href": "/message/new",
            "unread": True,
            "has_attachment": False,
        }
    ]
    client.async_get_grades.return_value = [
        {
            "subject": "Matematyka",
            "grade": "5",
            "date": "2026-09-21",
            "category": "Test",
            "teacher": "Anna Nowak",
            "semester": 1,
            "type": "numeric",
        }
    ]
    client.async_get_homework.return_value = [
        SimpleNamespace(
            subject="Matematyka",
            category="Praca domowa",
            teacher="Anna Nowak",
            lesson="",
            task_date="2026-09-21",
            completion_date="2026-09-22",
            href="/homework/new",
        )
    ]
    client.async_get_schedule.return_value = [
        {
            "data": "2026-09-22",
            "tytul": "Sprawdzian",
            "przedmiot": "Matematyka",
            "godzina": "08:00",
            "numer_lekcji": 1,
            "szczegoly": {},
            "href": "/schedule/new",
        }
    ]
    client.async_get_timetable.return_value = [
        {
            "data": "2026-09-22",
            "dzien_tygodnia": "Wtorek",
            "numer": 1,
            "przedmiot": "Matematyka",
            "nauczyciel_sala": "Anna Nowak, 12",
            "od": "08:00",
            "do": "08:45",
            "przerwa_od": "",
            "przerwa_do": "",
            "odwolana": False,
            "zastepstwo": True,
            "info": "Zastepstwo",
            "szczegoly": {},
        }
    ]

    await coordinator._async_update_data()
    await hass.async_block_till_done()

    unsubscribe()
    assert {event_type: len(events) for event_type, events in received.items()} == {
        EVENT_NOWA_WIADOMOSC: 1,
        EVENT_NOWA_OCENA: 1,
        EVENT_NOWE_ZADANIE: 1,
        EVENT_NOWE_ZDARZENIE: 1,
        EVENT_ZMIANA_PLANU: 1,
    }



async def test_after_bootstrap_only_requested_sources_are_polled(
    hass: HomeAssistant,
) -> None:
    """Enabled entity contexts decide which Librus endpoints are refreshed."""
    entry = _entry()
    client = _client()
    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)

    # First refresh bootstraps all sources before platforms exist.
    await coordinator._async_update_data()
    for method in (
        client.async_get_student_information,
        client.async_get_grades,
        client.async_get_messages,
        client.async_get_homework,
        client.async_get_schedule,
        client.async_get_timetable,
    ):
        method.reset_mock()

    unsubscribe = coordinator.async_add_listener(
        lambda: None, frozenset({SOURCE_TIMETABLE})
    )
    try:
        await coordinator._async_update_data()
    finally:
        unsubscribe()

    client.async_get_timetable.assert_awaited_once()
    client.async_get_student_information.assert_not_awaited()
    client.async_get_grades.assert_not_awaited()
    client.async_get_messages.assert_not_awaited()
    client.async_get_homework.assert_not_awaited()
    client.async_get_schedule.assert_not_awaited()


async def test_no_enabled_entity_contexts_make_no_api_requests(
    hass: HomeAssistant,
) -> None:
    """After bootstrap, disabling every entity avoids all polling requests."""
    entry = _entry()
    client = _client()
    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)

    await coordinator._async_update_data()
    for method in (
        client.async_get_student_information,
        client.async_get_grades,
        client.async_get_messages,
        client.async_get_homework,
        client.async_get_schedule,
        client.async_get_timetable,
    ):
        method.reset_mock()

    result = await coordinator._async_update_data()

    assert result["plan_lekcji"] == []
    client.async_get_student_information.assert_not_awaited()
    client.async_get_grades.assert_not_awaited()
    client.async_get_messages.assert_not_awaited()
    client.async_get_homework.assert_not_awaited()
    client.async_get_schedule.assert_not_awaited()
    client.async_get_timetable.assert_not_awaited()


async def test_context_matrix_calendar_only_polls_only_timetable(
    hass: HomeAssistant,
) -> None:
    """Calendar-only context polls only the timetable after bootstrap."""
    entry = _entry()
    client = _client()
    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)

    await coordinator._async_update_data()
    for method in (
        client.async_get_student_information,
        client.async_get_grades,
        client.async_get_messages,
        client.async_get_homework,
        client.async_get_schedule,
        client.async_get_timetable,
    ):
        method.reset_mock()

    unsubscribe = coordinator.async_add_listener(
        lambda: None, frozenset({SOURCE_TIMETABLE})
    )
    try:
        await coordinator._async_update_data()
    finally:
        unsubscribe()

    client.async_get_timetable.assert_awaited_once()
    client.async_get_student_information.assert_not_awaited()
    client.async_get_grades.assert_not_awaited()
    client.async_get_messages.assert_not_awaited()
    client.async_get_homework.assert_not_awaited()
    client.async_get_schedule.assert_not_awaited()


async def test_context_matrix_calendar_plus_grades_polls_two_sources(
    hass: HomeAssistant,
) -> None:
    """Calendar plus grades polls exactly timetable and grades."""
    entry = _entry()
    client = _client()
    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)

    await coordinator._async_update_data()
    for method in (
        client.async_get_student_information,
        client.async_get_grades,
        client.async_get_messages,
        client.async_get_homework,
        client.async_get_schedule,
        client.async_get_timetable,
    ):
        method.reset_mock()

    unsub_calendar = coordinator.async_add_listener(
        lambda: None, frozenset({SOURCE_TIMETABLE})
    )
    unsub_grades = coordinator.async_add_listener(
        lambda: None, frozenset({"grades"})
    )
    try:
        await coordinator._async_update_data()
    finally:
        unsub_grades()
        unsub_calendar()

    client.async_get_timetable.assert_awaited_once()
    client.async_get_grades.assert_awaited_once()
    client.async_get_student_information.assert_not_awaited()
    client.async_get_messages.assert_not_awaited()
    client.async_get_homework.assert_not_awaited()
    client.async_get_schedule.assert_not_awaited()


async def test_context_source_stops_after_entity_context_is_removed(
    hass: HomeAssistant,
) -> None:
    """Removing a context immediately stops polling its source."""
    entry = _entry()
    client = _client()
    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)

    await coordinator._async_update_data()
    for method in (
        client.async_get_messages,
        client.async_get_timetable,
    ):
        method.reset_mock()

    unsub_calendar = coordinator.async_add_listener(
        lambda: None, frozenset({SOURCE_TIMETABLE})
    )
    unsub_messages = coordinator.async_add_listener(
        lambda: None, frozenset({"messages"})
    )

    await coordinator._async_update_data()
    client.async_get_timetable.assert_awaited_once()
    client.async_get_messages.assert_awaited_once()

    client.async_get_timetable.reset_mock()
    client.async_get_messages.reset_mock()
    unsub_messages()

    try:
        await coordinator._async_update_data()
    finally:
        unsub_calendar()

    client.async_get_timetable.assert_awaited_once()
    client.async_get_messages.assert_not_awaited()


async def test_reenabled_source_seeds_cache_without_false_events(
    hass: HomeAssistant,
) -> None:
    """Re-enabling a source seeds its current data instead of firing backlog events."""
    entry = _entry()
    client = _client()
    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)
    received = []
    hass.bus.async_listen(EVENT_NOWA_WIADOMOSC, received.append)

    await coordinator._async_update_data()

    unsub_messages = coordinator.async_add_listener(
        lambda: None, frozenset({"messages"})
    )
    await coordinator._async_update_data()
    unsub_messages()

    # One refresh without messages removes the source from initialized sources.
    unsub_calendar = coordinator.async_add_listener(
        lambda: None, frozenset({SOURCE_TIMETABLE})
    )
    await coordinator._async_update_data()

    client.async_get_messages.return_value = [
        {
            "author": "Sekretariat",
            "title": "Existing while disabled",
            "date": "2026-09-22",
            "href": "/message/existing",
            "unread": True,
            "has_attachment": False,
        }
    ]

    unsub_messages = coordinator.async_add_listener(
        lambda: None, frozenset({"messages"})
    )
    try:
        await coordinator._async_update_data()
        await hass.async_block_till_done()
    finally:
        unsub_messages()
        unsub_calendar()

    assert received == []
