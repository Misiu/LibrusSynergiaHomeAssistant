"""Platforma czujników dla integracji Librus APIX."""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import DEFAULT_PLAN_DAYS
from .coordinator import LibrusConfigEntry, LibrusDataUpdateCoordinator
from .entity import LibrusEntity
from .plan_lekcji import (
    biezacy_dzien,
    dni_do_wyswietlenia,
    lekcje_dnia,
    nastepna_lekcja,
    polacz_z_wydarzeniami,
)

PARALLEL_UPDATES = 0



def _srednia_ocen(oceny: List[Dict]) -> Optional[float]:
    """Oblicz srednia ocen z listy ocen."""
    wartosci = []
    for g in oceny:
        grade_str = g.get("ocena", "")
        try:
            base = float(grade_str[0])
            if len(grade_str) > 1:
                if "+" in grade_str:
                    base += 0.5
                elif "-" in grade_str:
                    base -= 0.25
            wartosci.append(base)
        except (ValueError, IndexError):
            continue
    return round(sum(wartosci) / len(wartosci), 2) if wartosci else None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: LibrusConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Konfiguracja platformy czujnikow Librus APIX."""
    coordinator = config_entry.runtime_data

    entities: List[SensorEntity] = [
        LibrusUczenSensor(coordinator, config_entry),
        LibrusSzczesliwyNumerekSensor(coordinator, config_entry),
        LibrusOcenySensor(coordinator, config_entry),
        LibrusWiadomosciSensor(coordinator, config_entry),
        LibrusZadaniaSensor(coordinator, config_entry),
        LibrusTerminarzSensor(coordinator, config_entry),
        LibrusPlanLekcjiSensor(coordinator, config_entry),
        LibrusNastepnaLekcjaSensor(coordinator, config_entry),
        LibrusSredniaOcenSensor(coordinator, config_entry),
    ]
    async_add_entities(entities)

    known_subjects: set[str] = set()

    @callback
    def _add_subject_entities() -> None:
        """Dodaj encje dla przedmiotow, ktore pojawily sie po setupie."""
        subjects = set(
            (coordinator.data or {}).get("oceny_wg_przedmiotu", {})
        )
        new_subjects = sorted(subjects - known_subjects)
        if not new_subjects:
            return

        subject_entities: List[SensorEntity] = []
        for subject in new_subjects:
            subject_entities.extend(
                [
                    LibrusPrzedmiotSensor(coordinator, subject, config_entry),
                    LibrusSredniaPrzedmiotuSensor(
                        coordinator, subject, config_entry
                    ),
                ]
            )

        known_subjects.update(new_subjects)
        async_add_entities(subject_entities)

    _add_subject_entities()
    config_entry.async_on_unload(
        coordinator.async_add_listener(_add_subject_entities)
    )


def _lekcja_do_atrybutu(lekcja: Dict[str, Any]) -> Dict[str, Any]:
    """Okrojona lekcja do atrybutu encji.

    Pomijamy godziny przerw - nie uzywa ich zadna karta, a przy pelnym tygodniu
    to setki bajtow zblizajacych stan do limitu recordera (16 KB).
    """
    return {k: v for k, v in lekcja.items() if k not in ("przerwa_od", "przerwa_do")}


class LibrusUczenSensor(LibrusEntity, SensorEntity):
    """Czujnik z informacjami o uczniu."""

    _availability_key = "student_info"

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: LibrusConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator, config_entry)
        self._attr_translation_key = "student_information"
        self._attr_unique_id = f"{config_entry.entry_id}_uczen"
        self._attr_icon = "mdi:account-school"

    @property
    def native_value(self) -> Optional[str]:
        info = (self.coordinator.data or {}).get("student_info")
        return info.name if info else None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        info = (self.coordinator.data or {}).get("student_info")
        if not info:
            return {}
        return {
            "klasa": info.class_name,
            "numer_w_klasie": info.number,
            "wychowawca": info.tutor,
            "szkola": info.school,
            "szczesliwy_numerek": info.lucky_number,
        }


class LibrusSzczesliwyNumerekSensor(LibrusEntity, SensorEntity):
    """Czujnik ze szczesliwym numerkiem dnia."""

    _availability_key = "student_info"

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: LibrusConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator, config_entry)
        self._attr_translation_key = "lucky_number"
        self._attr_unique_id = f"{config_entry.entry_id}_szczesliwy_numerek"
        self._attr_icon = "mdi:numeric"

    @property
    def native_value(self) -> Any:
        info = (self.coordinator.data or {}).get("student_info")
        return info.lucky_number if info else None


class LibrusOcenySensor(LibrusEntity, SensorEntity):
    """Czujnik z wszystkimi ocenami pogrupowanymi wedlug przedmiotow."""

    _availability_key = "grades"

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: LibrusConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator, config_entry)
        self._attr_translation_key = "grades"
        self._attr_unique_id = f"{config_entry.entry_id}_oceny"
        self._attr_icon = "mdi:school"

    @property
    def native_value(self) -> int:
        return len((self.coordinator.data or {}).get("oceny", []))

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        data = self.coordinator.data or {}
        oceny_wg_przedmiotu = data.get("oceny_wg_przedmiotu", {})
        sa_nowe = any(
            g["jest_nowa"]
            for grades in oceny_wg_przedmiotu.values()
            for g in grades
        )
        return {
            "oceny_wg_przedmiotu": oceny_wg_przedmiotu,
            "liczba_ocen": len((self.coordinator.data or {}).get("oceny", [])),
            "liczba_przedmiotow": len(oceny_wg_przedmiotu),
            "sa_nowe_oceny": sa_nowe,
            "semestr": data.get("semestr_biezacy"),
        }


class LibrusPrzedmiotSensor(LibrusEntity, SensorEntity):
    """Czujnik z ocenami dla konkretnego przedmiotu."""

    _availability_key = "grades"

    def __init__(
        self,
        coordinator: LibrusDataUpdateCoordinator,
        subject: str,
        config_entry: LibrusConfigEntry,
    ) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator, config_entry)
        self._subject = subject
        safe_name = subject.lower().replace(" ", "_").replace("/", "_")
        self._attr_translation_key = "subject_grades"
        self._attr_translation_placeholders = {"subject": subject}
        self._attr_unique_id = f"{config_entry.entry_id}_przedmiot_{safe_name}"
        self._attr_icon = "mdi:book-open-variant"

    @property
    def native_value(self) -> Optional[str]:
        oceny = (self.coordinator.data or {}).get("oceny_wg_przedmiotu", {}).get(self._subject, [])
        if not oceny:
            return None
        return ", ".join(g["ocena"] for g in oceny)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        oceny = (self.coordinator.data or {}).get("oceny_wg_przedmiotu", {}).get(self._subject, [])
        if not oceny:
            return {}

        srednia = _srednia_ocen(oceny)

        # Najnowsza ocena wg daty
        najnowsza: Optional[Dict] = None
        najnowsza_data: Optional[date] = None
        for g in oceny:
            for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
                try:
                    d = datetime.strptime(g["data"].strip(), fmt).date()
                    if najnowsza_data is None or d > najnowsza_data:
                        najnowsza_data = d
                        najnowsza = g
                    break
                except ValueError:
                    continue

        return {
            "oceny": oceny,
            "lista_ocen": ", ".join(g["ocena"] for g in oceny),
            "srednia": srednia,
            "najnowsza_ocena": najnowsza,
            "sa_nowe_oceny": any(g["jest_nowa"] for g in oceny),
        }


class LibrusSredniaOcenSensor(LibrusEntity, SensorEntity):
    """Czujnik ze srednia wszystkich ocen biezacego semestru (do wykresu)."""

    _availability_key = "grades"

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: LibrusConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator, config_entry)
        self._attr_translation_key = "average_grade"
        self._attr_unique_id = f"{config_entry.entry_id}_srednia_ocen"
        self._attr_icon = "mdi:chart-line"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = None

    @property
    def native_value(self) -> Optional[float]:
        data = self.coordinator.data or {}
        wszystkie = [
            g
            for oceny in data.get("oceny_wg_przedmiotu", {}).values()
            for g in oceny
        ]
        return _srednia_ocen(wszystkie)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        data = self.coordinator.data or {}
        srednie_przedmiotow = {
            subject: _srednia_ocen(oceny)
            for subject, oceny in data.get("oceny_wg_przedmiotu", {}).items()
            if _srednia_ocen(oceny) is not None
        }
        return {
            "srednie_wg_przedmiotow": srednie_przedmiotow,
            "semestr": data.get("semestr_biezacy"),
        }


class LibrusSredniaPrzedmiotuSensor(LibrusEntity, SensorEntity):
    """Czujnik ze srednia ocen dla konkretnego przedmiotu (do wykresu)."""

    _availability_key = "grades"

    def __init__(
        self,
        coordinator: LibrusDataUpdateCoordinator,
        subject: str,
        config_entry: LibrusConfigEntry,
    ) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator, config_entry)
        self._subject = subject
        safe_name = subject.lower().replace(" ", "_").replace("/", "_")
        self._attr_translation_key = "subject_average"
        self._attr_translation_placeholders = {"subject": subject}
        self._attr_unique_id = f"{config_entry.entry_id}_srednia_{safe_name}"
        self._attr_icon = "mdi:chart-bar"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = None

    @property
    def native_value(self) -> Optional[float]:
        oceny = (self.coordinator.data or {}).get("oceny_wg_przedmiotu", {}).get(self._subject, [])
        return _srednia_ocen(oceny)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        oceny = (self.coordinator.data or {}).get("oceny_wg_przedmiotu", {}).get(self._subject, [])
        return {
            "przedmiot": self._subject,
            "lista_ocen": ", ".join(g["ocena"] for g in oceny),
            "liczba_ocen": len(oceny),
        }


class LibrusTerminarzSensor(LibrusEntity, SensorEntity):
    """Czujnik z nadchodzacymi zdarzeniami z kalendarza Librusa (biezacy + nastepny miesiac)."""

    _availability_key = "schedule"

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: LibrusConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator, config_entry)
        self._attr_translation_key = "schedule"
        self._attr_unique_id = f"{config_entry.entry_id}_terminarz"
        self._attr_icon = "mdi:calendar-month"

    @property
    def native_value(self) -> int:
        return len((self.coordinator.data or {}).get("terminarz", []))

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        terminarz = (self.coordinator.data or {}).get("terminarz", [])
        typy: Dict[str, int] = {}
        for z in terminarz:
            t = z.get("tytul", "")
            typy[t] = typy.get(t, 0) + 1
        return {
            "zdarzenia": terminarz,
            "liczba_zdarzen": len(terminarz),
            "typy": typy,
        }


class LibrusZadaniaSensor(LibrusEntity, SensorEntity):
    """Czujnik z nadchodzacymi zadaniami i sprawdzianami (30 dni do przodu)."""

    _availability_key = "homework"

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: LibrusConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator, config_entry)
        self._attr_translation_key = "homework"
        self._attr_unique_id = f"{config_entry.entry_id}_zadania"
        self._attr_icon = "mdi:calendar-check"

    @property
    def native_value(self) -> int:
        return len((self.coordinator.data or {}).get("zadania", []))

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        zadania = (self.coordinator.data or {}).get("zadania", [])
        kategorie: Dict[str, int] = {}
        for z in zadania:
            k = z.get("kategoria", "")
            kategorie[k] = kategorie.get(k, 0) + 1
        return {
            "zadania": zadania,
            "liczba_zadan": len(zadania),
            "kategorie": kategorie,
        }


class _OdswiezanieCominutowe:
    """Przelicza stan encji co minute, lokalnie i bez odpytywania Librusa.

    Koordynator odswieza dane co kilka godzin, a oba czujniki planu zaleza od
    biezacego czasu (trwajaca lekcja, dzien do pokazania). Home Assistant nie
    zapisuje stanu, gdy nic sie nie zmienilo, wiec jest to tanie.
    """

    async def async_added_to_hass(self) -> None:
        """Uruchom cykliczne przeliczanie stanu."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_przelicz, timedelta(minutes=1)
            )
        )

    @callback
    def _async_przelicz(self, _now) -> None:
        self.async_write_ha_state()

    def _teraz(self) -> datetime:
        """Lokalny czas HA bez strefy - godziny z Librusa tez sa lokalne."""
        return dt_util.now().replace(tzinfo=None)


class LibrusPlanLekcjiSensor(_OdswiezanieCominutowe, LibrusEntity, SensorEntity):
    """Czujnik z planem lekcji (biezacy i nastepny tydzien)."""

    _availability_key = "timetable"

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: LibrusConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator, config_entry)
        self._attr_translation_key = "lesson_timetable"
        self._attr_unique_id = f"{config_entry.entry_id}_plan_lekcji"
        self._attr_icon = "mdi:timetable"

    def _plan(self) -> List[Dict]:
        return (self.coordinator.data or {}).get("plan_lekcji", [])

    @property
    def native_value(self) -> int:
        """Liczba lekcji zaplanowanych na dzisiaj."""
        return len(lekcje_dnia(self._plan(), self._teraz().date()))

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        dane = self.coordinator.data or {}
        plan = self._plan()
        teraz = self._teraz()
        dzis = teraz.date()

        # Osiem dni kalendarzowych zawsze zawiera co najmniej DEFAULT_PLAN_DAYS
        # dni roboczych - takze wtedy, gdy dzisiejsze lekcje juz sie skonczyly
        # i dzisiaj wypada z planu. Pelne dwa tygodnie niepotrzebnie rozdymaja
        # stan encji zapisywany przez recorder.
        okno = [
            l for l in plan
            if dzis.strftime("%Y-%m-%d") <= l["data"] <= (dzis + timedelta(days=7)).strftime("%Y-%m-%d")
        ]
        okno, wydarzenia_dnia, zadania_dnia = polacz_z_wydarzeniami(
            okno, dane.get("terminarz"), dane.get("zadania")
        )

        # Dzien znika, gdy skonczy sie jego ostatnia lekcja - ta sama zasada
        # rzadzi wyborem dnia do pokazania i zawartoscia planu tygodnia.
        tydzien = dni_do_wyswietlenia(okno, teraz, DEFAULT_PLAN_DAYS)
        biezacy = biezacy_dzien(okno, teraz)
        dzisiaj = lekcje_dnia(okno, dzis)
        zmiany = [
            _lekcja_do_atrybutu(l) for lekcje in tydzien.values() for l in lekcje
            if l["zastepstwo"] or l["odwolana"]
        ]

        # Recorder w HA odrzuca stan powyzej 16 KB atrybutow, dlatego lekcje
        # wystawiamy tylko raz - w "tydzien". Dzien do pokazania wskazuje
        # "biezacy_dzien_data", czyli klucz w tym samym slowniku.
        return {
            "tydzien": {
                data: [_lekcja_do_atrybutu(l) for l in lekcje]
                for data, lekcje in tydzien.items()
            },
            "biezacy_dzien_data": biezacy[0]["data"] if biezacy else None,
            "biezacy_dzien_nazwa": biezacy[0]["dzien_tygodnia"] if biezacy else None,
            "wydarzenia_dnia": wydarzenia_dnia,
            "zadania_dnia": zadania_dnia,
            "liczba_lekcji_dzisiaj": len(dzisiaj),
            "pierwsza_lekcja": dzisiaj[0]["od"] if dzisiaj else None,
            "ostatnia_lekcja": dzisiaj[-1]["do"] if dzisiaj else None,
            "zmiany": zmiany,
            "sa_zmiany": bool(zmiany),
        }


class LibrusNastepnaLekcjaSensor(_OdswiezanieCominutowe, LibrusEntity, SensorEntity):
    """Czujnik z trwajaca lub najblizsza lekcja."""

    _availability_key = "timetable"

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: LibrusConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator, config_entry)
        self._attr_translation_key = "next_lesson"
        self._attr_unique_id = f"{config_entry.entry_id}_nastepna_lekcja"
        self._attr_icon = "mdi:clock-start"

    def _lekcja(self) -> Optional[Dict]:
        plan = (self.coordinator.data or {}).get("plan_lekcji", [])
        return nastepna_lekcja(plan, self._teraz())

    @property
    def native_value(self) -> Optional[str]:
        lekcja = self._lekcja()
        return lekcja["przedmiot"] if lekcja else None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        lekcja = self._lekcja()
        if not lekcja:
            return {}
        return {
            "data": lekcja["data"],
            "dzien_tygodnia": lekcja["dzien_tygodnia"],
            "numer": lekcja["numer"],
            "od": lekcja["od"],
            "do": lekcja["do"],
            "nauczyciel_sala": lekcja["nauczyciel_sala"],
            "za_minut": lekcja["za_minut"],
            "trwa_teraz": lekcja["trwa_teraz"],
            "zastepstwo": lekcja["zastepstwo"],
            "info": lekcja["info"],
        }


class LibrusWiadomosciSensor(LibrusEntity, SensorEntity):
    """Czujnik z wiadomosciami (temat i nadawca, bez pobierania tresci)."""

    _availability_key = "messages"

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: LibrusConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator, config_entry)
        self._attr_translation_key = "messages"
        self._attr_unique_id = f"{config_entry.entry_id}_wiadomosci"
        self._attr_icon = "mdi:message-text"

    @property
    def native_value(self) -> int:
        """Liczba nieprzeczytanych wiadomosci."""
        msgs = (self.coordinator.data or {}).get("wiadomosci", [])
        return sum(1 for m in msgs if m.get("unread", False))

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        msgs = (self.coordinator.data or {}).get("wiadomosci", [])[:5]
        return {
            "wiadomosci": [
                {
                    "nadawca": m["author"],
                    "temat": m["title"],
                    "data": m["date"],
                    "nieprzeczytana": m.get("unread", False),
                    "jest_nowa": m.get("jest_nowa", False),
                    "ma_zalacznik": m.get("has_attachment", False),
                }
                for m in msgs
            ],
            "liczba_nieprzeczytanych": sum(1 for m in msgs if m.get("unread", False)),
            "sa_nowe_wiadomosci": any(m.get("jest_nowa", False) for m in msgs),
        }
