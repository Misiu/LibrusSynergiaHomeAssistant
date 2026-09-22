"""Test the Librus Synergia integration."""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.components.homeassistant import (
    DOMAIN as HOMEASSISTANT_DOMAIN,
    SERVICE_UPDATE_ENTITY,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from librus_apix.exceptions import AuthorizationError, MaintananceError

from custom_components.librus.const import DOMAIN


def _dzis() -> date:
    """Dzisiejsza data wedlug strefy Home Assistanta.

    Czujniki uzywaja dt_util.now(), a nie zegara systemowego. W testach HA
    stoi na UTC, wiec date.today() rozjezdzalo sie o jeden dzien w oknie
    00:00-02:00 czasu lokalnego (i zaleznie od strefy runnera w CI).
    """
    return dt_util.now().date()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Wlacz ladowanie custom_components w testach."""
    return


def _lekcja(numer, przedmiot, od, do, dzien=None, zastepstwo=False, odwolana=False):
    """Zbuduj wpis planu lekcji w formacie zwracanym przez async_get_timetable."""
    dzien = dzien or _dzis()
    return {
        "data": dzien.strftime("%Y-%m-%d"),
        "dzien_tygodnia": "Poniedziałek",
        "numer": numer,
        "przedmiot": przedmiot,
        "nauczyciel_sala": "12",
        "od": od,
        "do": do,
        "przerwa_od": None,
        "przerwa_do": None,
        "odwolana": odwolana,
        "zastepstwo": zastepstwo,
        "info": "Zastepstwo" if zastepstwo else ("Lekcja odwolana" if odwolana else ""),
        "szczegoly": {},
    }



def _entity_id(
    hass: HomeAssistant, platform: str, entry: MockConfigEntry, suffix: str
) -> str:
    """Znajdz entity_id po stabilnym unique_id integracji."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{suffix}"
    )
    assert entity_id is not None
    return entity_id


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Librus",
        data={"username": "test_user", "password": "test_password"},
    )


@pytest.fixture
def mock_librus_client() -> MagicMock:
    """Return a mock Librus client."""
    client = MagicMock()
    client.async_authenticate = AsyncMock(return_value=True)
    client.async_get_student_information = AsyncMock(
        return_value=SimpleNamespace(
            name="Jan Kowalski",
            class_name="8A",
            number=7,
            tutor="Anna Nowak",
            school="SP nr 1",
            lucky_number=13,
        )
    )
    client.async_get_grades = AsyncMock(return_value=[
        {
            "subject": "Matematyka",
            "grade": "5",
            "date": "2025-01-01",
            "category": "Test",
            "teacher": "Jan Kowalski",
            "semester": 1,
            "type": "numeric",
        }
    ])
    client.async_get_messages = AsyncMock(return_value=[])
    client.async_get_homework = AsyncMock(return_value=[])
    client.async_get_schedule = AsyncMock(return_value=[])
    client.async_get_timetable = AsyncMock(return_value=[
        _lekcja(1, "Matematyka", "08:00", "08:45"),
        _lekcja(2, "Fizyka", "09:00", "09:45", zastepstwo=True),
        _lekcja(1, "Historia", "08:00", "08:45", dzien=_dzis() + timedelta(days=1)),
    ])
    return client


async def _setup(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    client: MagicMock,
    *,
    enable_legacy_plan: bool = False,
    enable_entities: tuple[str, ...] = (),
) -> None:
    """Skonfiguruj integracje z zamockowanym klientem."""
    entry.add_to_hass(hass)
    with patch("custom_components.librus.LibrusApiClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        suffixes = list(enable_entities)
        if enable_legacy_plan:
            suffixes.append("plan_lekcji")

        if suffixes:
            registry = er.async_get(hass)
            for suffix in suffixes:
                entity_id = _entity_id(hass, "sensor", entry, suffix)
                entity_entry = registry.async_get(entity_id)
                assert entity_entry is not None
                assert (
                    entity_entry.disabled_by
                    is er.RegistryEntryDisabler.INTEGRATION
                )
                registry.async_update_entity(entity_id, disabled_by=None)

            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()

            for suffix in suffixes:
                entity_id = _entity_id(hass, "sensor", entry, suffix)
                assert hass.states.get(entity_id) is not None


async def test_setup_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Coordinator jest przechowywany w runtime_data wpisu config entry."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    coordinator = mock_config_entry.runtime_data
    assert coordinator.client is mock_librus_client
    assert coordinator.config_entry is mock_config_entry
    assert coordinator.data["student_info"].name == "Jan Kowalski"


async def test_unload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Unload usuwa encje obu platform i zatrzymuje coordinator."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    sensor_id = _entity_id(hass, "sensor", mock_config_entry, "nastepna_lekcja")
    calendar_id = _entity_id(
        hass, "calendar", mock_config_entry, "plan_lekcji_calendar"
    )

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is config_entries.ConfigEntryState.NOT_LOADED
    assert hass.states.get(sensor_id).state == "unavailable"
    assert hass.states.get(calendar_id).state == "unavailable"


async def test_plan_lekcji_sensor(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Czujnik planu lekcji wystawia dzisiejsze lekcje i wykryte zmiany."""
    # Ostatnia lekcja konczy sie o 23:59, wiec dzien jest "biezacy" niezaleznie
    # od tego, o ktorej uruchomiono testy.
    mock_librus_client.async_get_timetable.return_value = [
        _lekcja(1, "Matematyka", "00:00", "00:45"),
        _lekcja(2, "Fizyka", "23:10", "23:59", zastepstwo=True),
        _lekcja(1, "Historia", "08:00", "08:45", dzien=_dzis() + timedelta(days=1)),
    ]

    await _setup(
        hass,
        mock_config_entry,
        mock_librus_client,
        enable_legacy_plan=True,
    )

    stan = hass.states.get(_entity_id(hass, "sensor", mock_config_entry, "plan_lekcji"))
    assert stan is not None
    assert stan.state == "2"
    assert stan.attributes["pierwsza_lekcja"] == "00:00"
    assert stan.attributes["ostatnia_lekcja"] == "23:59"
    jutro = (_dzis() + timedelta(days=1)).strftime("%Y-%m-%d")
    assert [l["przedmiot"] for l in stan.attributes["tydzien"][jutro]] == ["Historia"]
    assert stan.attributes["sa_zmiany"] is True
    assert [l["przedmiot"] for l in stan.attributes["zmiany"]] == ["Fizyka"]


async def test_nastepna_lekcja_sensor(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Czujnik nastepnej lekcji wybiera pierwsza lekcje, ktora sie nie skonczyla."""
    mock_librus_client.async_get_timetable.return_value = [
        _lekcja(1, "Matematyka", "00:00", "00:01"),
        _lekcja(2, "Fizyka", "23:58", "23:59"),
    ]

    await _setup(hass, mock_config_entry, mock_librus_client)

    stan = hass.states.get(_entity_id(hass, "sensor", mock_config_entry, "nastepna_lekcja"))
    assert stan is not None
    assert stan.state == "Fizyka"
    assert stan.attributes["numer"] == 2
    assert stan.attributes["od"] == "23:58"


async def test_plan_lekcji_przeskakuje_na_kolejny_dzien(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Po ostatniej lekcji dnia czujnik pokazuje plan nastepnego dnia."""
    jutro = _dzis() + timedelta(days=1)
    mock_librus_client.async_get_timetable.return_value = [
        # Dzisiejsze lekcje sa juz po czasie (koncza sie o 00:01).
        _lekcja(1, "Matematyka", "00:00", "00:01"),
        _lekcja(1, "Historia", "08:00", "08:45", dzien=jutro),
        _lekcja(2, "Chemia", "09:00", "09:45", dzien=jutro),
    ]

    await _setup(
        hass,
        mock_config_entry,
        mock_librus_client,
        enable_legacy_plan=True,
    )

    stan = hass.states.get(_entity_id(hass, "sensor", mock_config_entry, "plan_lekcji"))
    assert [l["przedmiot"] for l in stan.attributes["tydzien"][stan.attributes["biezacy_dzien_data"]]] == [
        "Historia",
        "Chemia",
    ]
    assert stan.attributes["biezacy_dzien_data"] == jutro.strftime("%Y-%m-%d")
    assert stan.attributes["biezacy_dzien_nazwa"]

    # Zakonczony dzien znika rowniez z planu tygodnia.
    assert list(stan.attributes["tydzien"]) == [jutro.strftime("%Y-%m-%d")]

    # Liczniki nadal opisuja doslownie dzisiaj.
    assert stan.attributes["liczba_lekcji_dzisiaj"] == 1


async def test_plan_lekcji_trzyma_sie_dzis_w_trakcie_zajec(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Dopoki trwa ostatnia lekcja, pokazywany jest biezacy dzien."""
    mock_librus_client.async_get_timetable.return_value = [
        _lekcja(1, "Matematyka", "00:00", "23:59"),
        _lekcja(1, "Historia", "08:00", "08:45", dzien=_dzis() + timedelta(days=1)),
    ]

    await _setup(
        hass,
        mock_config_entry,
        mock_librus_client,
        enable_legacy_plan=True,
    )

    stan = hass.states.get(_entity_id(hass, "sensor", mock_config_entry, "plan_lekcji"))
    assert [l["przedmiot"] for l in stan.attributes["tydzien"][stan.attributes["biezacy_dzien_data"]]] == ["Matematyka"]
    assert stan.attributes["biezacy_dzien_data"] == _dzis().strftime("%Y-%m-%d")


async def test_plan_lekcji_zaznacza_wydarzenia_i_zadania(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Kartkowka trafia na swoja lekcje, wywiadowka do wydarzen calodniowych."""
    dzis = _dzis().strftime("%Y-%m-%d")
    mock_librus_client.async_get_timetable.return_value = [
        _lekcja(1, "matematyka", "00:00", "00:45"),
        _lekcja(4, "fizyka", "23:10", "23:59"),
    ]
    mock_librus_client.async_get_schedule.return_value = [
        {
            "data": dzis, "tydzien": "Wednesday", "tytul": "kartkówka",
            "przedmiot": "fizyka", "godzina": "unknown", "numer_lekcji": 4,
            "szczegoly": {"Nauczyciel": "Anna Nowak", "Opis": "wielkości fizyczne"},
            "href": "",
        },
        {
            "data": dzis, "tydzien": "Wednesday", "tytul": "godz.: 17:00",
            "przedmiot": "Wywiadówka: zebranie rodziców", "godzina": "17:00",
            "numer_lekcji": "unknown", "szczegoly": {}, "href": "",
        },
    ]
    mock_librus_client.async_get_homework.return_value = [
        SimpleNamespace(
            subject="matematyka", category="Praca domowa", teacher="Danuta Kowalska",
            lesson="", task_date=dzis, completion_date=dzis, href="",
        )
    ]

    await _setup(
        hass,
        mock_config_entry,
        mock_librus_client,
        enable_legacy_plan=True,
    )

    stan = hass.states.get(_entity_id(hass, "sensor", mock_config_entry, "plan_lekcji"))
    lekcje = {l["przedmiot"]: l for l in stan.attributes["tydzien"][stan.attributes["biezacy_dzien_data"]]}

    assert [w["tytul"] for w in lekcje["fizyka"]["wydarzenia"]] == ["kartkówka"]
    assert lekcje["fizyka"]["wydarzenia"][0]["opis"] == "wielkości fizyczne"
    assert [z["kategoria"] for z in lekcje["matematyka"]["zadania"]] == ["Praca domowa"]
    assert lekcje["matematyka"]["wydarzenia"] == []

    calodniowe = stan.attributes["wydarzenia_dnia"][dzis]
    assert [w["przedmiot"] for w in calodniowe] == ["Wywiadówka: zebranie rodziców"]


async def test_plan_tygodnia_zawsze_pokazuje_piec_dni(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Po ostatniej lekcji dnia w planie nadal jest piec dni lekcyjnych."""
    dzis = _dzis()
    # Dzisiejsze lekcje juz sie skonczyly, kolejne szesc dni ma zajecia.
    plan = [_lekcja(1, "matematyka", "00:00", "00:01")]
    for i in range(1, 7):
        plan.append(
            _lekcja(1, f"przedmiot{i}", "08:00", "08:45", dzien=dzis + timedelta(days=i))
        )
    mock_librus_client.async_get_timetable.return_value = plan

    await _setup(
        hass,
        mock_config_entry,
        mock_librus_client,
        enable_legacy_plan=True,
    )

    stan = hass.states.get(_entity_id(hass, "sensor", mock_config_entry, "plan_lekcji"))
    tydzien = stan.attributes["tydzien"]

    assert len(tydzien) == 5, f"oczekiwano 5 dni, jest {len(tydzien)}: {list(tydzien)}"
    # Zakonczone dzis nie zajmuje miejsca w limicie.
    assert dzis.strftime("%Y-%m-%d") not in tydzien
    assert list(tydzien)[0] == (dzis + timedelta(days=1)).strftime("%Y-%m-%d")
    assert list(tydzien)[-1] == (dzis + timedelta(days=5)).strftime("%Y-%m-%d")


async def test_sensor_i_calendar_korzystaja_z_jednego_cyklu_api(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Legacy sensor is disabled by default; calendar uses the bootstrap fetch."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    sensor_id = _entity_id(hass, "sensor", mock_config_entry, "plan_lekcji")
    calendar_id = _entity_id(
        hass, "calendar", mock_config_entry, "plan_lekcji_calendar"
    )
    registry = er.async_get(hass)
    sensor_entry = registry.async_get(sensor_id)

    assert sensor_entry is not None
    assert sensor_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(sensor_id) is None
    assert hass.states.get(calendar_id) is not None
    assert mock_librus_client.async_get_timetable.await_count == 1


async def test_nowy_przedmiot_dodaje_encje_po_refreshu(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Nowy przedmiot po pierwszym setupie dostaje sensor i sensor sredniej."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    registry = er.async_get(hass)
    chemia_unique = f"{mock_config_entry.entry_id}_przedmiot_chemia"
    srednia_unique = f"{mock_config_entry.entry_id}_srednia_chemia"
    assert registry.async_get_entity_id("sensor", DOMAIN, chemia_unique) is None

    mock_librus_client.async_get_grades.return_value = [
        {
            "subject": "Matematyka",
            "grade": "5",
            "date": "2026-09-01",
            "category": "Test",
            "teacher": "Jan Kowalski",
            "semester": 1,
            "type": "numeric",
        },
        {
            "subject": "Chemia",
            "grade": "4",
            "date": "2026-09-20",
            "category": "Kartkowka",
            "teacher": "Anna Nowak",
            "semester": 1,
            "type": "numeric",
        },
    ]

    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    chemia_id = registry.async_get_entity_id("sensor", DOMAIN, chemia_unique)
    srednia_id = registry.async_get_entity_id("sensor", DOMAIN, srednia_unique)
    assert chemia_id is not None
    assert srednia_id is not None

    chemia_entry = registry.async_get(chemia_id)
    srednia_entry = registry.async_get(srednia_id)
    assert chemia_entry is not None
    assert srednia_entry is not None
    assert chemia_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert srednia_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(chemia_id) is None
    assert hass.states.get(srednia_id) is None

    registry.async_update_entity(chemia_id, disabled_by=None)
    registry.async_update_entity(srednia_id, disabled_by=None)

    with patch(
        "custom_components.librus.LibrusApiClient",
        return_value=mock_librus_client,
    ):
        assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get(chemia_id).state == "4"
    assert hass.states.get(srednia_id).state == "4.0"


async def test_wszystkie_encje_maja_to_samo_urzadzenie(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Sensory i kalendarz sa przypiete do jednego urzadzenia Librus."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, mock_config_entry.entry_id)
    assert len(entries) >= 12

    device_ids = {entry.device_id for entry in entries}
    assert None not in device_ids
    assert len(device_ids) == 1



async def test_default_disabled_entities_are_registered_but_not_loaded(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Optional sensors are disabled by default for new installations."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    registry = er.async_get(hass)
    for suffix in (
        "uczen",
        "szczesliwy_numerek",
        "zadania",
        "srednia_ocen",
        "terminarz",
        "plan_lekcji",
    ):
        entity_id = _entity_id(hass, "sensor", mock_config_entry, suffix)
        entry = registry.async_get(entity_id)
        assert entry is not None
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(entity_id) is None


async def test_exactly_four_primary_entities_are_enabled_by_default(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """A new installation exposes exactly the four primary entities."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(
        registry, mock_config_entry.entry_id
    )
    enabled = {
        (entry.domain, entry.unique_id)
        for entry in entries
        if entry.disabled_by is None
    }

    assert enabled == {
        ("sensor", f"{mock_config_entry.entry_id}_oceny"),
        ("sensor", f"{mock_config_entry.entry_id}_wiadomosci"),
        ("sensor", f"{mock_config_entry.entry_id}_nastepna_lekcja"),
        ("calendar", f"{mock_config_entry.entry_id}_plan_lekcji_calendar"),
    }


async def test_dynamic_subject_entities_are_disabled_by_default(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Per-subject grade entities do not expand the default entity set."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    registry = er.async_get(hass)
    for suffix in ("przedmiot_matematyka", "srednia_matematyka"):
        entity_id = _entity_id(hass, "sensor", mock_config_entry, suffix)
        entry = registry.async_get(entity_id)
        assert entry is not None
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(entity_id) is None


async def test_default_polling_skips_sources_used_only_by_disabled_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """After bootstrap, disabled student/homework entities cause no requests."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    for method in (
        mock_librus_client.async_get_student_information,
        mock_librus_client.async_get_grades,
        mock_librus_client.async_get_messages,
        mock_librus_client.async_get_homework,
        mock_librus_client.async_get_schedule,
        mock_librus_client.async_get_timetable,
    ):
        method.reset_mock()

    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    mock_librus_client.async_get_student_information.assert_not_awaited()
    mock_librus_client.async_get_homework.assert_not_awaited()
    mock_librus_client.async_get_schedule.assert_not_awaited()
    mock_librus_client.async_get_grades.assert_awaited_once()
    mock_librus_client.async_get_messages.assert_awaited_once()
    mock_librus_client.async_get_timetable.assert_awaited_once()


async def test_enabling_homework_sensor_restores_homework_polling(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Enabling an optional entity adds its source to later refreshes."""
    await _setup(
        hass,
        mock_config_entry,
        mock_librus_client,
        enable_entities=("zadania",),
    )

    for method in (
        mock_librus_client.async_get_student_information,
        mock_librus_client.async_get_homework,
    ):
        method.reset_mock()

    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    mock_librus_client.async_get_homework.assert_awaited_once()
    mock_librus_client.async_get_student_information.assert_not_awaited()


async def test_setup_bad_credentials_triggers_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Odrzucone dane logowania powinny uruchomic reauth w HA."""
    mock_config_entry.add_to_hass(hass)
    mock_librus_client.async_authenticate.return_value = False
    mock_librus_client.last_auth_error = AuthorizationError("bad credentials")

    with patch(
        "custom_components.librus.LibrusApiClient",
        return_value=mock_librus_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state.name == "SETUP_ERROR"
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(flow["context"]["source"] == config_entries.SOURCE_REAUTH for flow in flows)


async def test_setup_maintenance_is_retryable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Maintenance Librusa nie powinien byc traktowany jako zle haslo."""
    mock_config_entry.add_to_hass(hass)
    mock_librus_client.async_authenticate.return_value = False
    mock_librus_client.last_auth_error = MaintananceError("maintenance")

    with patch(
        "custom_components.librus.LibrusApiClient",
        return_value=mock_librus_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state.name == "SETUP_RETRY"
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert not any(flow["context"]["source"] == config_entries.SOURCE_REAUTH for flow in flows)



async def test_glowne_sensory_wystawiaja_spojne_dane(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Sprawdz podstawowe stany i atrybuty calego zestawu sensorow."""
    today = _dzis().strftime("%Y-%m-%d")
    mock_librus_client.async_get_messages.return_value = [
        {
            "author": "Sekretariat",
            "title": "Informacja",
            "date": today,
            "href": "/message/1",
            "unread": True,
            "has_attachment": True,
        }
    ]
    mock_librus_client.async_get_homework.return_value = [
        SimpleNamespace(
            subject="Matematyka",
            category="Praca domowa",
            teacher="Anna Nowak",
            lesson="",
            task_date=today,
            completion_date=today,
            href="/homework/1",
        )
    ]
    mock_librus_client.async_get_schedule.return_value = [
        {
            "data": today,
            "tydzien": "Poniedziałek",
            "tytul": "Sprawdzian",
            "przedmiot": "Matematyka",
            "godzina": "08:00",
            "numer_lekcji": 1,
            "szczegoly": {},
            "href": "/schedule/1",
        }
    ]

    await _setup(
        hass,
        mock_config_entry,
        mock_librus_client,
        enable_entities=(
            "uczen",
            "szczesliwy_numerek",
            "zadania",
            "srednia_ocen",
            "terminarz",
            "przedmiot_matematyka",
            "srednia_matematyka",
        ),
    )

    uczen = hass.states.get(
        _entity_id(hass, "sensor", mock_config_entry, "uczen")
    )
    lucky = hass.states.get(
        _entity_id(hass, "sensor", mock_config_entry, "szczesliwy_numerek")
    )
    oceny = hass.states.get(
        _entity_id(hass, "sensor", mock_config_entry, "oceny")
    )
    wiadomosci = hass.states.get(
        _entity_id(hass, "sensor", mock_config_entry, "wiadomosci")
    )
    zadania = hass.states.get(
        _entity_id(hass, "sensor", mock_config_entry, "zadania")
    )
    terminarz = hass.states.get(
        _entity_id(hass, "sensor", mock_config_entry, "terminarz")
    )
    srednia = hass.states.get(
        _entity_id(hass, "sensor", mock_config_entry, "srednia_ocen")
    )
    matematyka = hass.states.get(
        _entity_id(hass, "sensor", mock_config_entry, "przedmiot_matematyka")
    )
    srednia_matematyka = hass.states.get(
        _entity_id(hass, "sensor", mock_config_entry, "srednia_matematyka")
    )

    assert uczen.state == "Jan Kowalski"
    assert uczen.attributes["klasa"] == "8A"
    assert lucky.state == "13"
    assert oceny.state == "1"
    assert oceny.attributes["liczba_przedmiotow"] == 1
    assert wiadomosci.state == "1"
    assert wiadomosci.attributes["wiadomosci"][0]["ma_zalacznik"] is True
    assert zadania.state == "1"
    assert zadania.attributes["kategorie"] == {"Praca domowa": 1}
    assert terminarz.state == "1"
    assert terminarz.attributes["typy"] == {"Sprawdzian": 1}
    assert srednia.state == "5.0"
    assert matematyka.state == "5"
    assert srednia_matematyka.state == "5.0"


async def test_refresh_aktualizuje_sensory_bez_ponownego_setupu(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Zmiana danych coordinatora aktualizuje istniejace encje."""
    await _setup(
        hass,
        mock_config_entry,
        mock_librus_client,
        enable_entities=("szczesliwy_numerek",),
    )
    lucky_id = _entity_id(
        hass, "sensor", mock_config_entry, "szczesliwy_numerek"
    )
    assert hass.states.get(lucky_id).state == "13"

    mock_librus_client.async_get_student_information.return_value = SimpleNamespace(
        name="Jan Kowalski",
        class_name="8A",
        number=7,
        tutor="Anna Nowak",
        school="SP nr 1",
        lucky_number=21,
    )

    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(lucky_id).state == "21"



async def test_coordinator_ma_staly_interwal_dwie_godziny(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Polling interval jest ustalony przez integracje, nie przez uzytkownika."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    assert mock_config_entry.runtime_data.update_interval == timedelta(hours=2)


async def test_encje_uzywaja_nowych_nazw_home_assistant(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Nazwy encji lacza nazwe urzadzenia z przetlumaczona nazwa encji."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    sensor_id = _entity_id(hass, "sensor", mock_config_entry, "nastepna_lekcja")
    calendar_id = _entity_id(
        hass, "calendar", mock_config_entry, "plan_lekcji_calendar"
    )

    assert (
        hass.states.get(sensor_id).attributes["friendly_name"]
        == "Librus - Jan Kowalski Next lesson"
    )
    assert (
        hass.states.get(calendar_id).attributes["friendly_name"]
        == "Librus - Jan Kowalski Lesson timetable"
    )


async def test_pelna_awaria_oznacza_encje_jako_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Pelna awaria API ustawia stan coordinatora i encji na unavailable."""
    await _setup(hass, mock_config_entry, mock_librus_client)
    sensor_id = _entity_id(hass, "sensor", mock_config_entry, "oceny")

    mock_librus_client.async_get_student_information.return_value = None
    mock_librus_client.async_get_grades.return_value = None
    mock_librus_client.async_get_messages.return_value = None
    mock_librus_client.async_get_homework.return_value = None
    mock_librus_client.async_get_schedule.return_value = None
    mock_librus_client.async_get_timetable.return_value = None

    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data.last_update_success is False
    assert hass.states.get(sensor_id).state == "unavailable"



async def test_czesciowa_awaria_oznacza_tylko_powiazane_encje_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Awaria wiadomosci nie moze zdejmowac ocen, planu ani kalendarza."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    messages_id = _entity_id(hass, "sensor", mock_config_entry, "wiadomosci")
    grades_id = _entity_id(hass, "sensor", mock_config_entry, "oceny")
    calendar_id = _entity_id(
        hass, "calendar", mock_config_entry, "plan_lekcji_calendar"
    )

    mock_librus_client.async_get_messages.return_value = None

    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data.last_update_success is True
    assert hass.states.get(messages_id).state == "unavailable"
    assert hass.states.get(grades_id).state != "unavailable"
    assert hass.states.get(calendar_id).state != "unavailable"


async def test_awaria_timetable_oznacza_plan_i_calendar_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Awaria timetable oznacza aktywne encje planu jako unavailable."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    next_id = _entity_id(
        hass, "sensor", mock_config_entry, "nastepna_lekcja"
    )
    calendar_id = _entity_id(
        hass, "calendar", mock_config_entry, "plan_lekcji_calendar"
    )

    mock_librus_client.async_get_timetable.return_value = None

    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(next_id).state == "unavailable"
    assert hass.states.get(calendar_id).state == "unavailable"


async def test_homeassistant_update_entity_refreshes_shared_coordinator(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_librus_client: MagicMock,
) -> None:
    """Generic update refreshes the shared coordinator context-aware."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    plan_id = _entity_id(hass, "sensor", mock_config_entry, "nastepna_lekcja")
    initial_timetable_calls = mock_librus_client.async_get_timetable.await_count
    initial_student_calls = (
        mock_librus_client.async_get_student_information.await_count
    )
    initial_homework_calls = mock_librus_client.async_get_homework.await_count

    assert await async_setup_component(hass, HOMEASSISTANT_DOMAIN, {})

    await hass.services.async_call(
        HOMEASSISTANT_DOMAIN,
        SERVICE_UPDATE_ENTITY,
        {"entity_id": plan_id},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert (
        mock_librus_client.async_get_timetable.await_count
        == initial_timetable_calls + 1
    )
    assert (
        mock_librus_client.async_get_student_information.await_count
        == initial_student_calls
    )
    assert (
        mock_librus_client.async_get_homework.await_count
        == initial_homework_calls
    )
