"""Wspolny koordynator danych dla integracji Librus APIX."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TypedDict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from librus_apix.exceptions import AuthorizationError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _current_semester() -> int:
    """Zwroc numer biezacego semestru wg polskiego roku szkolnego."""
    month = dt_util.now().month
    return 1 if month >= 9 or month == 1 else 2


def _jest_nowa(date_str: str) -> bool:
    """Sprawdz czy data miesci sie w ostatnich 24 godzinach (dzis lub wczoraj)."""
    if not date_str:
        return False
    wczoraj = dt_util.now().date() - timedelta(days=1)
    for fmt in (
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            d = datetime.strptime(date_str.strip(), fmt).date()
            return d >= wczoraj
        except ValueError:
            continue
    return False


EVENT_NOWA_WIADOMOSC = f"{DOMAIN}_nowa_wiadomosc"
EVENT_NOWA_OCENA = f"{DOMAIN}_nowa_ocena"
EVENT_NOWE_ZADANIE = f"{DOMAIN}_nowe_zadanie"
EVENT_NOWE_ZDARZENIE = f"{DOMAIN}_nowe_zdarzenie"
EVENT_ZMIANA_PLANU = f"{DOMAIN}_zmiana_planu"


class LibrusCoordinatorData(TypedDict):
    """Dane udostepniane encjom przez wspolny coordinator."""

    student_info: Any
    oceny: List[Dict[str, Any]]
    oceny_wg_przedmiotu: Dict[str, List[Dict[str, Any]]]
    wiadomosci: List[Dict[str, Any]]
    zadania: List[Dict[str, Any]]
    terminarz: List[Dict[str, Any]]
    plan_lekcji: List[Dict[str, Any]]
    semestr_biezacy: int
    availability: Dict[str, bool]


type LibrusConfigEntry = ConfigEntry[LibrusDataUpdateCoordinator]

UPDATE_INTERVAL = timedelta(hours=2)


class LibrusDataUpdateCoordinator(DataUpdateCoordinator[LibrusCoordinatorData]):
    """Klasa zarzadzajaca pobieraniem danych z Librus."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: LibrusConfigEntry,
        client: Any,
    ) -> None:
        """Inicjalizacja koordynatora."""
        self.client = client
        self._seen_message_hrefs: set = set()
        self._seen_grade_ids: set = set()
        self._seen_homework_ids: set = set()
        self._seen_schedule_ids: set = set()
        self._seen_plan_ids: set = set()
        self._unavailable_sources: set[str] = set()
        self._first_run: bool = True
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )

    async def _async_update_data(self) -> LibrusCoordinatorData:
        """Pobierz aktualne dane z API Librus."""
        current_sem = _current_semester()

        try:
            student_info = await self.client.async_get_student_information()
            self._raise_if_auth_failed()

            grades = await self.client.async_get_grades()
            self._raise_if_auth_failed()

            messages = await self.client.async_get_messages(count=10)
            self._raise_if_auth_failed()

            homework_raw = await self.client.async_get_homework()
            self._raise_if_auth_failed()

            schedule_raw = await self.client.async_get_schedule()
            self._raise_if_auth_failed()

            plan_raw = await self.client.async_get_timetable()
            self._raise_if_auth_failed()

            if all(
                value is None
                for value in (
                    student_info,
                    grades,
                    messages,
                    homework_raw,
                    schedule_raw,
                    plan_raw,
                )
            ):
                raise UpdateFailed("Librus API is unavailable")

            availability = {
                "student_info": student_info is not None,
                "grades": grades is not None,
                "messages": messages is not None,
                "homework": homework_raw is not None,
                "schedule": schedule_raw is not None,
                "timetable": plan_raw is not None,
            }
            self._log_source_availability(availability)

            prev = self.data or {}

            if grades is None:
                if "oceny" not in prev:
                    raise UpdateFailed("Nie udalo sie pobrac ocen i brak danych w cache")
                grades = prev.get("oceny", [])
                oceny_wg_przedmiotu = prev.get("oceny_wg_przedmiotu", {})
            else:
                oceny_wg_przedmiotu: Dict[str, List[Dict]] = {}
                for grade in grades:
                    subject = grade["subject"]
                    if subject not in oceny_wg_przedmiotu:
                        oceny_wg_przedmiotu[subject] = []
                    oceny_wg_przedmiotu[subject].append({
                        "ocena": grade["grade"],
                        "data": grade["date"],
                        "kategoria": grade["category"],
                        "nauczyciel": grade["teacher"],
                        "semestr": grade.get("semester"),
                        "jest_nowa": _jest_nowa(grade["date"]),
                    })

            student_info = student_info or prev.get("student_info")
            wiadomosci = (
                self._build_wiadomosci(messages)
                if messages is not None
                else prev.get("wiadomosci", [])
            )
            zadania = (
                self._build_zadania(homework_raw)
                if homework_raw is not None
                else prev.get("zadania", [])
            )
            terminarz = (
                schedule_raw if schedule_raw is not None else prev.get("terminarz", [])
            )
            plan_lekcji = (
                plan_raw if plan_raw is not None else prev.get("plan_lekcji", [])
            )

            result = {
                "student_info": student_info,
                "oceny": grades,
                "oceny_wg_przedmiotu": oceny_wg_przedmiotu,
                "wiadomosci": wiadomosci,
                "zadania": zadania,
                "terminarz": terminarz,
                "plan_lekcji": plan_lekcji,
                "semestr_biezacy": current_sem,
                "availability": availability,
            }

            # Pierwsze pobranie - tylko zapamietaj stan, nie wysylaj powiadomien
            if self._first_run:
                self._first_run = False
                for msg in wiadomosci:
                    self._seen_message_hrefs.add(msg["href"])
                for grade in grades:
                    self._seen_grade_ids.add(
                        (grade["subject"], grade["date"], grade["grade"])
                    )
                for zadanie in zadania:
                    self._seen_homework_ids.add(
                        (zadanie["przedmiot"], zadanie["termin"], zadanie["kategoria"])
                    )
                for zdarzenie in terminarz:
                    self._seen_schedule_ids.add(
                        (zdarzenie["data"], zdarzenie["tytul"], zdarzenie["przedmiot"])
                    )
                for lekcja in plan_lekcji:
                    if lekcja["zastepstwo"] or lekcja["odwolana"]:
                        self._seen_plan_ids.add(
                            (lekcja["data"], lekcja["numer"], lekcja["info"])
                        )
            else:
                self._fire_events(wiadomosci, grades)
                self._fire_homework_events(zadania)
                self._fire_schedule_events(terminarz)
                self._fire_plan_events(plan_lekcji)

            return result

        except (ConfigEntryAuthFailed, UpdateFailed):
            raise
        except Exception as err:
            raise UpdateFailed(f"Blad komunikacji z API: {err}") from err

    def _log_source_availability(self, availability: dict[str, bool]) -> None:
        """Log source availability transitions without repeating messages."""
        unavailable = {
            source for source, is_available in availability.items() if not is_available
        }

        for source in sorted(unavailable - self._unavailable_sources):
            _LOGGER.info("Librus data source %s is unavailable", source)

        for source in sorted(self._unavailable_sources - unavailable):
            _LOGGER.info("Librus data source %s is available again", source)

        self._unavailable_sources = unavailable

    def _raise_if_auth_failed(self) -> None:
        """Przerwij cykl natychmiast po odrzuceniu danych logowania."""
        if isinstance(
            getattr(self.client, "last_auth_error", None), AuthorizationError
        ):
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="invalid_auth",
            )

    def _fire_events(self, messages: List[Dict], grades: List[Dict]) -> None:
        """Wyslij zdarzenia HA dla nowych wiadomosci i ocen."""
        for msg in messages:
            href = msg.get("href", "")
            if href and href not in self._seen_message_hrefs:
                self._seen_message_hrefs.add(href)
                _LOGGER.debug("Nowa wiadomosc: %s", msg.get("title"))
                self.hass.bus.fire(
                    EVENT_NOWA_WIADOMOSC,
                    {
                        "nadawca": msg.get("author", ""),
                        "temat": msg.get("title", ""),
                        "data": msg.get("date", ""),
                        "ma_zalacznik": msg.get("has_attachment", False),
                    },
                )

        for grade in grades:
            grade_id = (grade["subject"], grade["date"], grade["grade"])
            if grade_id not in self._seen_grade_ids:
                self._seen_grade_ids.add(grade_id)
                _LOGGER.debug("Nowa ocena: %s %s", grade["subject"], grade["grade"])
                self.hass.bus.fire(
                    EVENT_NOWA_OCENA,
                    {
                        "przedmiot": grade["subject"],
                        "ocena": grade["grade"],
                        "data": grade["date"],
                        "kategoria": grade["category"],
                        "nauczyciel": grade["teacher"],
                    },
                )

    def _fire_schedule_events(self, terminarz: List[Dict]) -> None:
        """Wyslij zdarzenia HA dla nowych zdarzen w kalendarzu."""
        for zdarzenie in terminarz:
            ev_id = (zdarzenie["data"], zdarzenie["tytul"], zdarzenie["przedmiot"])
            if ev_id not in self._seen_schedule_ids:
                self._seen_schedule_ids.add(ev_id)
                _LOGGER.debug("Nowe zdarzenie: %s %s %s", zdarzenie["data"], zdarzenie["przedmiot"], zdarzenie["tytul"])
                self.hass.bus.fire(
                    EVENT_NOWE_ZDARZENIE,
                    {
                        "data": zdarzenie["data"],
                        "tytul": zdarzenie["tytul"],
                        "przedmiot": zdarzenie["przedmiot"],
                        "godzina": zdarzenie["godzina"],
                    },
                )

    def _fire_plan_events(self, plan: List[Dict]) -> None:
        """Wyslij zdarzenia HA dla nowych zastepstw i odwolanych lekcji."""
        for lekcja in plan:
            if not (lekcja["zastepstwo"] or lekcja["odwolana"]):
                continue
            plan_id = (lekcja["data"], lekcja["numer"], lekcja["info"])
            if plan_id in self._seen_plan_ids:
                continue
            self._seen_plan_ids.add(plan_id)
            _LOGGER.debug(
                "Zmiana w planie: %s lekcja %s - %s",
                lekcja["data"], lekcja["numer"], lekcja["info"],
            )
            self.hass.bus.fire(
                EVENT_ZMIANA_PLANU,
                {
                    "data": lekcja["data"],
                    "dzien_tygodnia": lekcja["dzien_tygodnia"],
                    "numer": lekcja["numer"],
                    "przedmiot": lekcja["przedmiot"],
                    "od": lekcja["od"],
                    "do": lekcja["do"],
                    "rodzaj": "odwolana" if lekcja["odwolana"] else "zastepstwo",
                    "info": lekcja["info"],
                },
            )

    def _build_wiadomosci(self, messages: Optional[List[Dict]]) -> List[Dict]:
        """Oznacz nowe wiadomosci i zwroc liste."""
        result = []
        for msg in messages or []:
            msg["jest_nowa"] = _jest_nowa(msg.get("date", ""))
            result.append(msg)
        return result

    def _build_zadania(self, homework_raw) -> List[Dict]:
        """Przetworz liste Homework na liste dict, posortowana po terminie."""
        if not homework_raw:
            return []
        zadania = [
            {
                "przedmiot": hw.subject,
                "kategoria": hw.category,
                "nauczyciel": hw.teacher,
                "lekcja": hw.lesson,
                "data_zadania": hw.task_date,
                "termin": hw.completion_date,
                "href": hw.href,
            }
            for hw in homework_raw
        ]
        return sorted(zadania, key=lambda z: z["termin"])

    def _fire_homework_events(self, zadania: List[Dict]) -> None:
        """Wyslij zdarzenia HA dla nowych zadan/sprawdzianow."""
        for zadanie in zadania:
            hw_id = (zadanie["przedmiot"], zadanie["termin"], zadanie["kategoria"])
            if hw_id not in self._seen_homework_ids:
                self._seen_homework_ids.add(hw_id)
                _LOGGER.debug("Nowe zadanie: %s %s", zadanie["przedmiot"], zadanie["kategoria"])
                self.hass.bus.fire(
                    EVENT_NOWE_ZADANIE,
                    {
                        "przedmiot": zadanie["przedmiot"],
                        "kategoria": zadanie["kategoria"],
                        "termin": zadanie["termin"],
                        "nauczyciel": zadanie["nauczyciel"],
                    },
                )


