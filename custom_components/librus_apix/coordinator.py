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

SOURCE_STUDENT_INFO = "student_info"
SOURCE_GRADES = "grades"
SOURCE_MESSAGES = "messages"
SOURCE_HOMEWORK = "homework"
SOURCE_SCHEDULE = "schedule"
SOURCE_TIMETABLE = "timetable"
ALL_SOURCES = frozenset(
    {
        SOURCE_STUDENT_INFO,
        SOURCE_GRADES,
        SOURCE_MESSAGES,
        SOURCE_HOMEWORK,
        SOURCE_SCHEDULE,
        SOURCE_TIMETABLE,
    }
)


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
        self._initialized_sources: set[str] = set()
        self._bootstrap_complete = False
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )

    def _requested_sources(self) -> set[str]:
        """Return sources needed by currently enabled coordinator entities."""
        if not self._bootstrap_complete:
            # The first refresh happens before platforms are forwarded, so there are
            # no entity contexts yet. Bootstrap all sources once to create the device
            # and dynamic subject entities. Later refreshes follow enabled entities.
            return set(ALL_SOURCES)

        requested: set[str] = set()
        for context in self.async_contexts():
            if isinstance(context, (set, frozenset)):
                requested.update(context)
            elif isinstance(context, str):
                requested.add(context)
        return requested

    async def _async_update_data(self) -> LibrusCoordinatorData:
        """Fetch only Librus data needed by enabled entities."""
        current_sem = _current_semester()
        prev = self.data or {}
        requested = self._requested_sources()

        if not requested:
            return {
                "student_info": prev.get("student_info"),
                "oceny": prev.get("oceny", []),
                "oceny_wg_przedmiotu": prev.get("oceny_wg_przedmiotu", {}),
                "wiadomosci": prev.get("wiadomosci", []),
                "zadania": prev.get("zadania", []),
                "terminarz": prev.get("terminarz", []),
                "plan_lekcji": prev.get("plan_lekcji", []),
                "semestr_biezacy": current_sem,
                "availability": prev.get("availability", {}),
            }

        availability = dict(prev.get("availability", {}))
        successful_source = False

        try:
            student_info = prev.get("student_info")
            if SOURCE_STUDENT_INFO in requested:
                fetched = await self.client.async_get_student_information()
                self._raise_if_auth_failed()
                availability[SOURCE_STUDENT_INFO] = fetched is not None
                if fetched is not None:
                    student_info = fetched
                    successful_source = True

            grades = prev.get("oceny", [])
            oceny_wg_przedmiotu = prev.get("oceny_wg_przedmiotu", {})
            if SOURCE_GRADES in requested:
                fetched_grades = await self.client.async_get_grades()
                self._raise_if_auth_failed()
                availability[SOURCE_GRADES] = fetched_grades is not None
                if fetched_grades is not None:
                    successful_source = True
                    grades = fetched_grades
                    oceny_wg_przedmiotu = {}
                    for grade in grades:
                        subject = grade["subject"]
                        oceny_wg_przedmiotu.setdefault(subject, []).append(
                            {
                                "ocena": grade["grade"],
                                "data": grade["date"],
                                "kategoria": grade["category"],
                                "nauczyciel": grade["teacher"],
                                "semestr": grade.get("semester"),
                                "jest_nowa": _jest_nowa(grade["date"]),
                            }
                        )

            wiadomosci = prev.get("wiadomosci", [])
            if SOURCE_MESSAGES in requested:
                messages = await self.client.async_get_messages(count=10)
                self._raise_if_auth_failed()
                availability[SOURCE_MESSAGES] = messages is not None
                if messages is not None:
                    successful_source = True
                    wiadomosci = self._build_wiadomosci(messages)

            zadania = prev.get("zadania", [])
            if SOURCE_HOMEWORK in requested:
                homework_raw = await self.client.async_get_homework()
                self._raise_if_auth_failed()
                availability[SOURCE_HOMEWORK] = homework_raw is not None
                if homework_raw is not None:
                    successful_source = True
                    zadania = self._build_zadania(homework_raw)

            terminarz = prev.get("terminarz", [])
            if SOURCE_SCHEDULE in requested:
                schedule_raw = await self.client.async_get_schedule()
                self._raise_if_auth_failed()
                availability[SOURCE_SCHEDULE] = schedule_raw is not None
                if schedule_raw is not None:
                    successful_source = True
                    terminarz = schedule_raw

            plan_lekcji = prev.get("plan_lekcji", [])
            if SOURCE_TIMETABLE in requested:
                plan_raw = await self.client.async_get_timetable()
                self._raise_if_auth_failed()
                availability[SOURCE_TIMETABLE] = plan_raw is not None
                if plan_raw is not None:
                    successful_source = True
                    plan_lekcji = plan_raw

            if not successful_source:
                raise UpdateFailed("Librus API is unavailable")

            for source in ALL_SOURCES:
                availability.setdefault(source, True)
            self._log_source_availability(availability)

            result: LibrusCoordinatorData = {
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

            # If a source was disabled, do not emit a backlog of custom events
            # when it is enabled again. Its first successful fetch seeds the cache.
            self._initialized_sources.intersection_update(requested)
            self._process_events(
                requested,
                availability,
                wiadomosci,
                grades,
                zadania,
                terminarz,
                plan_lekcji,
            )
            self._bootstrap_complete = True
            return result

        except (ConfigEntryAuthFailed, UpdateFailed):
            raise
        except Exception as err:
            raise UpdateFailed(f"Blad komunikacji z API: {err}") from err

    def _process_events(
        self,
        requested: set[str],
        availability: dict[str, bool],
        messages: List[Dict],
        grades: List[Dict],
        homework: List[Dict],
        schedule: List[Dict],
        timetable: List[Dict],
    ) -> None:
        """Seed each source before emitting events from later updates."""
        sources = {
            "messages": (
                messages,
                lambda: self._seen_message_hrefs.update(
                    msg["href"] for msg in messages if msg.get("href")
                ),
                lambda: self._fire_events(messages, []),
            ),
            "grades": (
                grades,
                lambda: self._seen_grade_ids.update(
                    (grade["subject"], grade["date"], grade["grade"])
                    for grade in grades
                ),
                lambda: self._fire_events([], grades),
            ),
            "homework": (
                homework,
                lambda: self._seen_homework_ids.update(
                    (item["przedmiot"], item["termin"], item["kategoria"])
                    for item in homework
                ),
                lambda: self._fire_homework_events(homework),
            ),
            "schedule": (
                schedule,
                lambda: self._seen_schedule_ids.update(
                    (item["data"], item["tytul"], item["przedmiot"])
                    for item in schedule
                ),
                lambda: self._fire_schedule_events(schedule),
            ),
            "timetable": (
                timetable,
                lambda: self._seen_plan_ids.update(
                    (lesson["data"], lesson["numer"], lesson["info"])
                    for lesson in timetable
                    if lesson["zastepstwo"] or lesson["odwolana"]
                ),
                lambda: self._fire_plan_events(timetable),
            ),
        }

        for source, (_data, seed, fire) in sources.items():
            if source not in requested or not availability[source]:
                continue
            if source not in self._initialized_sources:
                seed()
                self._initialized_sources.add(source)
            else:
                fire()

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


