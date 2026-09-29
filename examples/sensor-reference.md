# Sensory Librus Synergia - Szczegółowe odwołanie

Integracja tworzy następujące sensory. Część z nich jest **wyłączona domyślnie** — możesz je włączyć w ustawieniach integracji.

## Sensory aktywne domyślnie

| Encja | Opis | Atrybut | Typ danych |
|--------|------|---------|------------|
| `sensor.librus_jan_maat_oceny` | Liczba ocen bieżącego semestru | `liczba_ocen` | int |
| `sensor.librus_jan_maat_wiadomosci` | Wiadomości bez otwierania w Librusie | `wiadomosci`, `liczba_nieprzeczytanych` | list, int |
| `sensor.librus_jan_maat_nastepna_lekcja` | Trwająca lub najbliższa lekcja | `dzien_tygodnia`, `numer`, `data`, `od`, `do`, `przedmiot`, `nauczyciel_sala`, `trwa_teraz`, `zastepstwo`, `za_minut` | str, bool, int |
| `calendar.librus_jan_maat_plan_lekcji` | Plan lekcji jako kalendarz HA | Wydarzenia z lekcjami | calendar |

## Sensory opcjonalne (domyślnie wyłączone)

| Encja | Opis | Włączenie | Źródło API |
|--------|------|-----------|------------|
| `sensor.librus_jan_maat_informacje_o_uczniu` | Klasa, wychowawca, szkoła | Developer Tools → Services | `student_info` |
| `sensor.librus_jan_maat_szczesliwy_numerek` | Szczęśliwy numerek dnia | Developer Tools → Services | `student_info` |
| `sensor.librus_jan_maat_srednia_ocen` | Globalna średnia ze wszystkich przedmiotów | Developer Tools → Services | `grades` |
| `sensor.librus_jan_maat_srednia_<przedmiot>` | Średnia z konkretnego przedmiotu | Developer Tools → Services | `grades` |
| `sensor.librus_jan_maat_<przedmiot>` | Oceny z konkretnego przedmiotu | Developer Tools → Services | `grades` |
| `sensor.librus_jan_maat_zadania` | Zadania domowe | Developer Tools → Services | `homework` |
| `sensor.librus_jan_maat_terminarz` | Terminarz (sprawdziany, kartkówki, wywiadówki) | Developer Tools → Services | `schedule` |
| `sensor.librus_jan_maat_plan_lekcji` | Legacy sensor planu lekcji | Developer Tools → Services | `timetable` |

## Jak włączyć sensor?

1. Otwórz **Settings → Devices & Services → Librus Synergia**
2. Kliknij na wpis integracji
3. Przejdź do **Entities**
4. Znajdź sensor, który chcesz włączyć
5. Kliknij na niego i zmień status na **Enabled**

## Znaczenie stanów i atrybutów

### sensor.librus_jan_maat_oceny
- **State**: liczba ocen
- **Atrybuty**: `oceny` (pełna lista ocen z przedmiotów)

### sensor.librus_jan_maat_wiadomosci
- **State**: liczba nieprzeczytanych wiadomości
- **Atrybuty**: `wiadomosci` (lista słowników z polami: `nadawca`, `temat`, `data`, `nieprzeczytana`, `ma_zalacznik`)

### sensor.librus_jan_maat_nastepna_lekcja
- **State**: nazwa przedmiotu
- **Atrybuty**:
  - `dzien_tygodnia` — dzień w słowach (Poniedziałek, Wtorek, ...)
  - `data` — data w formacie YYYY-MM-DD
  - `numer` — numer lekcji w dniu
  - `od` — godzina rozpoczęcia (HH:MM)
  - `do` — godzina zakończenia (HH:MM)
  - `nauczyciel_sala` — nauczyciel lub sala
  - `trwa_teraz` — True jeśli lekcja trwa w tej chwili
  - `zastepstwo` — True jeśli to zastępstwo
  - `za_minut` — liczba minut do startu lekcji (aktualizuje się co minutę lokalnie)

### sensor.librus_jan_maat_plan_lekcji (legacy)
- **State**: liczba lekcji dzisiaj
- **Atrybuty**:
  - `tydzien` — słownik: `{"data": [lekcje]}`
  - `biezacy_dzien_data` — data dnia do wyświetlenia
  - `biezacy_dzien_nazwa` — nazwa dnia w słowach
  - `biezacy_dzien_data` — data dnia
  - `события_дня` — zdarzenia przypiętе do dziś (z terminarza)
  - `zadania_dnia` — prace domowe przypiętе do dziś
  - `zmiany` — lista zmian w planie (zastępstwa, odwołania)
  - `sa_zmiany` — True jeśli są zmiany

## Planowanie - co pobiera każdy sensor?

| Sensor | Pobiera | Interwał |
|--------|---------|----------|
| Oceny | `grades` | co 2h |
| Wiadomości | `messages` | co 2h |
| Następna lekcja | `timetable` | co 2h (przelicza co minutę lokalnie) |
| Plan lekcji (legacy) | `timetable`, `schedule`, `homework` | co 2h |
| Informacje o uczniu | `student_info` | co 2h |
| Szczęśliwy numerek | `student_info` | co 2h |
| Zadania | `homework` | co 2h |
| Terminarz | `schedule` | co 2h |

## Filtrowanie atrybutów w szablonach

Przykład: pokazanie tylko nieprzeczytanych wiadomości:
```jinja2
{% set msg = state_attr('sensor.librus_jan_maat_wiadomosci', 'wiadomosci')
   | selectattr('nieprzeczytana', 'equalto', true) | list %}
{{ msg | length }} nieprzeczytanych
```

Przykład: pokazanie średnich z wszystkich przedmiotów:
```jinja2
{% set sensory = states | selectattr('entity_id', 'match', 'sensor.librus.*srednia_')
   | map(attribute='entity_id') | list %}
{% for s in sensory %}
  {{ state_attr(s, 'nazwa_przedmiotu') }}: {{ states(s) }}
{% endfor %}
```
