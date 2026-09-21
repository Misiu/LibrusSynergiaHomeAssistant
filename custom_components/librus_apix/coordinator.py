"""Wspolny koordynator danych dla integracji Librus APIX."""

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from librus_apix.exceptions import AuthorizationError

from .const import (
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _current_semester() -> int:
    """Zwroc numer biezacego semestru wg polskiego roku szkolnego."""
    month = date.today().month
    return 1 if month >= 9 or month == 1 else 2


def _interwal_odswiezania(config_entry: ConfigEntry) -> timedelta:
    """Odczytaj czestotliwosc odpytywania Librusa z opcji integracji."""
    minuty = config_entry.options.get(
        CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES
    )
    try:
        minuty = int(minuty)
    except (TypeError, ValueError):
        minuty = DEFAULT_SCAN_INTERVAL_MINUTES
    return timedelta(minutes=max(1, minuty))


def _jest_nowa(date_str: str) -> bool:
    """Sprawdz czy data miesci sie w ostatnich 24 godzinach (dzis lub wczoraj)."""
    if not date_str:
        return False
    wczoraj = date.today() - timedelta(days=1)
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


class LibrusDataUpdateCoordinator(DataUpdateCoordinator):
    """Klasa zarzadzajaca pobieraniem danych z Librus."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: Any,
        update_interval: timedelta,
    ) -> None:
        """Inicjalizacja koordynatora."""
        self.client = client
        self._seen_message_hrefs: set = set()
        self._seen_grade_ids: set = set()
        self._seen_homework_ids: set = set()
        self._seen_schedule_ids: set = set()
        self._seen_plan_ids: set = set()
        self._first_run: bool = True
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=update_interval,
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Pobierz aktualne dane z API Librus."""
        current_sem = _current_semester()

        try:
            student_info = await self.client.async_get_student_information()
            grades = await self.client.async_get_grades()
            messages = await self.client.async_get_messages(count=10)
            homework_raw = await self.client.async_get_homework()
            schedule_raw = await self.client.async_get_schedule()
            plan_raw = await self.client.async_get_timetable()

            if isinstance(
                getattr(self.client, "last_auth_error", None), AuthorizationError
            ):
                raise ConfigEntryAuthFailed("Librus rejected the credentials")

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

        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Blad komunikacji z API: {err}") from err

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


