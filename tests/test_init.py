"""Test the Librus APIX integration."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from librus_apix.exceptions import AuthorizationError, MaintananceError

from custom_components.librus_apix.const import DOMAIN


def _dzis() -> object:
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
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    """Skonfiguruj integracje z zamockowanym klientem."""
    entry.add_to_hass(hass)
    with patch("custom_components.librus_apix.LibrusApiClient", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_setup_entry(hass: HomeAssistant, mock_config_entry, mock_librus_client):
    """Coordinator jest przechowywany w runtime_data wpisu config entry."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    coordinator = mock_config_entry.runtime_data
    assert coordinator.client is mock_librus_client
    assert coordinator.config_entry is mock_config_entry
    assert coordinator.data["student_info"].name == "Jan Kowalski"


async def test_unload_entry(hass: HomeAssistant, mock_config_entry, mock_librus_client):
    """Unload usuwa encje obu platform i zatrzymuje coordinator."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    sensor_id = _entity_id(hass, "sensor", mock_config_entry, "plan_lekcji")
    calendar_id = _entity_id(
        hass, "calendar", mock_config_entry, "plan_lekcji_calendar"
    )

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is config_entries.ConfigEntryState.NOT_LOADED
    assert hass.states.get(sensor_id).state == "unavailable"
    assert hass.states.get(calendar_id).state == "unavailable"


async def test_plan_lekcji_sensor(hass: HomeAssistant, mock_config_entry, mock_librus_client):
    """Czujnik planu lekcji wystawia dzisiejsze lekcje i wykryte zmiany."""
    # Ostatnia lekcja konczy sie o 23:59, wiec dzien jest "biezacy" niezaleznie
    # od tego, o ktorej uruchomiono testy.
    mock_librus_client.async_get_timetable.return_value = [
        _lekcja(1, "Matematyka", "00:00", "00:45"),
        _lekcja(2, "Fizyka", "23:10", "23:59", zastepstwo=True),
        _lekcja(1, "Historia", "08:00", "08:45", dzien=_dzis() + timedelta(days=1)),
    ]

    await _setup(hass, mock_config_entry, mock_librus_client)

    stan = hass.states.get(_entity_id(hass, "sensor", mock_config_entry, "plan_lekcji"))
    assert stan is not None
    assert stan.state == "2"
    assert stan.attributes["pierwsza_lekcja"] == "00:00"
    assert stan.attributes["ostatnia_lekcja"] == "23:59"
    jutro = (_dzis() + timedelta(days=1)).strftime("%Y-%m-%d")
    assert [l["przedmiot"] for l in stan.attributes["tydzien"][jutro]] == ["Historia"]
    assert stan.attributes["sa_zmiany"] is True
    assert [l["przedmiot"] for l in stan.attributes["zmiany"]] == ["Fizyka"]


async def test_nastepna_lekcja_sensor(hass: HomeAssistant, mock_config_entry, mock_librus_client):
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
    hass: HomeAssistant, mock_config_entry, mock_librus_client
):
    """Po ostatniej lekcji dnia czujnik pokazuje plan nastepnego dnia."""
    jutro = _dzis() + timedelta(days=1)
    mock_librus_client.async_get_timetable.return_value = [
        # Dzisiejsze lekcje sa juz po czasie (koncza sie o 00:01).
        _lekcja(1, "Matematyka", "00:00", "00:01"),
        _lekcja(1, "Historia", "08:00", "08:45", dzien=jutro),
        _lekcja(2, "Chemia", "09:00", "09:45", dzien=jutro),
    ]

    await _setup(hass, mock_config_entry, mock_librus_client)

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
    hass: HomeAssistant, mock_config_entry, mock_librus_client
):
    """Dopoki trwa ostatnia lekcja, pokazywany jest biezacy dzien."""
    mock_librus_client.async_get_timetable.return_value = [
        _lekcja(1, "Matematyka", "00:00", "23:59"),
        _lekcja(1, "Historia", "08:00", "08:45", dzien=_dzis() + timedelta(days=1)),
    ]

    await _setup(hass, mock_config_entry, mock_librus_client)

    stan = hass.states.get(_entity_id(hass, "sensor", mock_config_entry, "plan_lekcji"))
    assert [l["przedmiot"] for l in stan.attributes["tydzien"][stan.attributes["biezacy_dzien_data"]]] == ["Matematyka"]
    assert stan.attributes["biezacy_dzien_data"] == _dzis().strftime("%Y-%m-%d")


async def test_plan_lekcji_zaznacza_wydarzenia_i_zadania(
    hass: HomeAssistant, mock_config_entry, mock_librus_client
):
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

    await _setup(hass, mock_config_entry, mock_librus_client)

    stan = hass.states.get(_entity_id(hass, "sensor", mock_config_entry, "plan_lekcji"))
    lekcje = {l["przedmiot"]: l for l in stan.attributes["tydzien"][stan.attributes["biezacy_dzien_data"]]}

    assert [w["tytul"] for w in lekcje["fizyka"]["wydarzenia"]] == ["kartkówka"]
    assert lekcje["fizyka"]["wydarzenia"][0]["opis"] == "wielkości fizyczne"
    assert [z["kategoria"] for z in lekcje["matematyka"]["zadania"]] == ["Praca domowa"]
    assert lekcje["matematyka"]["wydarzenia"] == []

    calodniowe = stan.attributes["wydarzenia_dnia"][dzis]
    assert [w["przedmiot"] for w in calodniowe] == ["Wywiadówka: zebranie rodziców"]


async def test_plan_tygodnia_zawsze_pokazuje_piec_dni(
    hass: HomeAssistant, mock_config_entry, mock_librus_client
):
    """Po ostatniej lekcji dnia w planie nadal jest piec dni lekcyjnych."""
    dzis = _dzis()
    # Dzisiejsze lekcje juz sie skonczyly, kolejne szesc dni ma zajecia.
    plan = [_lekcja(1, "matematyka", "00:00", "00:01")]
    for i in range(1, 7):
        plan.append(
            _lekcja(1, f"przedmiot{i}", "08:00", "08:45", dzien=dzis + timedelta(days=i))
        )
    mock_librus_client.async_get_timetable.return_value = plan

    await _setup(hass, mock_config_entry, mock_librus_client)

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
    """Sensor i calendar powstaja z jednego cyklu pobrania danych."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    sensor_id = _entity_id(hass, "sensor", mock_config_entry, "plan_lekcji")
    calendar_id = _entity_id(
        hass, "calendar", mock_config_entry, "plan_lekcji_calendar"
    )

    assert hass.states.get(sensor_id) is not None
    assert hass.states.get(calendar_id) is not None
    assert mock_librus_client.async_get_timetable.await_count == 1


async def test_nowy_przedmiot_dodaje_encje_po_refreshu(
    hass: HomeAssistant, mock_config_entry, mock_librus_client
):
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
    assert hass.states.get(chemia_id).state == "4"
    assert hass.states.get(srednia_id).state == "4.0"


async def test_wszystkie_encje_maja_to_samo_urzadzenie(
    hass: HomeAssistant, mock_config_entry, mock_librus_client
):
    """Sensory i kalendarz sa przypiete do jednego urzadzenia Librus."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, mock_config_entry.entry_id)
    assert len(entries) >= 12

    device_ids = {entry.device_id for entry in entries}
    assert None not in device_ids
    assert len(device_ids) == 1



async def test_setup_bad_credentials_triggers_reauth(
    hass: HomeAssistant, mock_config_entry, mock_librus_client
):
    """Odrzucone dane logowania powinny uruchomic reauth w HA."""
    mock_config_entry.add_to_hass(hass)
    mock_librus_client.async_authenticate.return_value = False
    mock_librus_client.last_auth_error = AuthorizationError("bad credentials")

    with patch(
        "custom_components.librus_apix.LibrusApiClient",
        return_value=mock_librus_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state.name == "SETUP_ERROR"
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(flow["context"]["source"] == config_entries.SOURCE_REAUTH for flow in flows)


async def test_setup_maintenance_is_retryable(
    hass: HomeAssistant, mock_config_entry, mock_librus_client
):
    """Maintenance Librusa nie powinien byc traktowany jako zle haslo."""
    mock_config_entry.add_to_hass(hass)
    mock_librus_client.async_authenticate.return_value = False
    mock_librus_client.last_auth_error = MaintananceError("maintenance")

    with patch(
        "custom_components.librus_apix.LibrusApiClient",
        return_value=mock_librus_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state.name == "SETUP_RETRY"
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert not any(flow["context"]["source"] == config_entries.SOURCE_REAUTH for flow in flows)



async def test_glowne_sensory_wystawiaja_spojne_dane(
    hass: HomeAssistant, mock_config_entry, mock_librus_client
):
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

    await _setup(hass, mock_config_entry, mock_librus_client)

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
    hass: HomeAssistant, mock_config_entry, mock_librus_client
):
    """Zmiana danych coordinatora aktualizuje istniejace encje."""
    await _setup(hass, mock_config_entry, mock_librus_client)
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
    hass: HomeAssistant, mock_config_entry, mock_librus_client
):
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

    sensor_id = _entity_id(hass, "sensor", mock_config_entry, "plan_lekcji")
    calendar_id = _entity_id(
        hass, "calendar", mock_config_entry, "plan_lekcji_calendar"
    )

    assert (
        hass.states.get(sensor_id).attributes["friendly_name"]
        == "Librus - Jan Kowalski Lesson timetable"
    )
    assert (
        hass.states.get(calendar_id).attributes["friendly_name"]
        == "Librus - Jan Kowalski Lesson timetable"
    )


async def test_pelna_awaria_oznacza_encje_jako_unavailable(
    hass: HomeAssistant, mock_config_entry, mock_librus_client
):
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
    hass: HomeAssistant, mock_config_entry, mock_librus_client
):
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
    hass: HomeAssistant, mock_config_entry, mock_librus_client
):
    """Awaria timetable dotyczy sensorow planu i natywnego kalendarza."""
    await _setup(hass, mock_config_entry, mock_librus_client)

    plan_id = _entity_id(hass, "sensor", mock_config_entry, "plan_lekcji")
    next_id = _entity_id(
        hass, "sensor", mock_config_entry, "nastepna_lekcja"
    )
    calendar_id = _entity_id(
        hass, "calendar", mock_config_entry, "plan_lekcji_calendar"
    )

    mock_librus_client.async_get_timetable.return_value = None

    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(plan_id).state == "unavailable"
    assert hass.states.get(next_id).state == "unavailable"
    assert hass.states.get(calendar_id).state == "unavailable"
