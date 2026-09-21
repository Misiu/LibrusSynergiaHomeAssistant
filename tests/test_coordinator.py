"""Testy wspolnego coordinatora Librus APIX."""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from librus_apix.exceptions import AuthorizationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.librus_apix.const import DOMAIN
from custom_components.librus_apix.coordinator import (
    LibrusDataUpdateCoordinator,
    _current_semester,
)


def _entry():
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Librus",
        data={"username": "test", "password": "secret"},
    )


def _client():
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
def test_current_semester(freezer, day, expected):
    """Styczen nadal nalezy do pierwszego semestru."""
    freezer.move_to(day)
    assert _current_semester() == expected


async def test_pierwszy_blad_ocen_bez_cache_powoduje_update_failed(hass):
    """Pierwsze pobranie nie moze udawac sukcesu bez danych o ocenach."""
    entry = _entry()
    client = _client()
    client.async_get_grades.return_value = None
    coordinator = LibrusDataUpdateCoordinator(hass, entry, client)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_pusty_cache_ocen_jest_poprawnym_cache(hass):
    """Uczen bez ocen nie traci dostepnosci przy chwilowym bledzie ocen."""
    entry = _entry()
    client = _client()
    client.async_get_student_information.return_value = None
    client.async_get_grades.return_value = None
    client.async_get_messages.return_value = None
    client.async_get_homework.return_value = None
    client.async_get_schedule.return_value = None
    client.async_get_timetable.return_value = None

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

    assert result["student_info"] is student
    assert result["oceny"] == []
    assert result["oceny_wg_przedmiotu"] == {}
    assert result["wiadomosci"] == []
    assert result["zadania"] == []
    assert result["terminarz"] == []
    assert result["plan_lekcji"] == []


async def test_czesciowy_blad_zachowuje_cache_innych_endpointow(hass):
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


async def test_coordinator_jest_powiazany_z_config_entry(hass):
    """HA 2026.9 powinien dostac config_entry jawnie w coordinatorze."""
    entry = _entry()
    coordinator = LibrusDataUpdateCoordinator(hass, entry, _client())

    assert coordinator.config_entry is entry
    assert coordinator.update_interval == timedelta(hours=2)



async def test_auth_rejection_przerywa_dalsze_endpointy(hass):
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



async def test_pelna_awaria_z_cache_nadal_jest_update_failed(hass):
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
