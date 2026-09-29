# 🎓 Librus Synergia for Home Assistant

Integracja Home Assistant z systemem Librus Synergia, umożliwiająca monitorowanie ocen, wiadomości i innych danych szkolnych.

**Domena integracji:** `librus`

## ✨ Funkcje

- 📊 **Monitoring ocen** - wszystkie oceny ze wszystkich przedmiotów
- 📈 **Statystyki** - średnie ocen, liczba ocen, trend
- 📧 **Wiadomości** - nadawca, temat, data i status najnowszych wiadomości bez otwierania ich w Librusie
- 🗓️ **Plan lekcji** - bieżący i następny tydzień, z zastępstwami i odwołanymi lekcjami
- 📅 **Kalendarz planu lekcji** - natywna encja `calendar` Home Assistanta z lekcjami jako wydarzeniami
- 🔔 **Powiadomienia** - automatyczne powiadomienia o nowych ocenach/wiadomościach
- 🏠 **Dashboard** - piękne karty w Home Assistant

## 🚀 Sensory

Integracja tworzy następujące sensory:

| Encja | Opis | Wartość |
|--------|------|---------|
| `sensor.librus_jan_maat_informacje_o_uczniu` | Informacje o uczniu (klasa, wychowawca, szkoła) | imię i nazwisko |
| `sensor.librus_jan_maat_szczesliwy_numerek` | Szczęśliwy numerek dnia | numer |
| `sensor.librus_jan_maat_oceny` | Wszystkie oceny bieżącego semestru | liczba ocen |
| `sensor.librus_jan_maat_srednia_ocen` | Globalna średnia ze wszystkich przedmiotów | float |
| `sensor.librus_jan_maat_wiadomosci` | Najnowsze wiadomości bez otwierania ich w Librusie | liczba nieprzeczytanych |
| `sensor.librus_jan_maat_zadania` | Zadania domowe | liczba zadań |
| `sensor.librus_jan_maat_terminarz` | Terminarz Librusa | liczba wydarzeń |
| `sensor.librus_jan_maat_plan_lekcji` | Legacy sensor planu lekcji | liczba lekcji dzisiaj |
| `sensor.librus_jan_maat_nastepna_lekcja` | Trwająca lub najbliższa lekcja | nazwa przedmiotu |
| `sensor.librus_jan_maat_matematyka` | Oceny z konkretnego przedmiotu | lista ocen, np. `4, 3+, 5` |
| `sensor.librus_jan_maat_srednia_matematyka` | Średnia z konkretnego przedmiotu | float |
| `calendar.librus_jan_maat_plan_lekcji` | Natywny kalendarz planu lekcji | bieżąca/najbliższa lekcja |

> Przykłady wyżej zakładają ucznia **Jan Maat** i polski język Home Assistanta.
> Home Assistant tworzy `entity_id` z nazwy urządzenia `Librus - <uczeń>` oraz
> przetłumaczonej nazwy encji, dlatego u Ciebie nazwy będą miały ten sam schemat,
> np. `sensor.librus_jan_maat_plan_lekcji`. Po utworzeniu encji jej `entity_id`
> można też ręcznie zmienić w Home Assistant.

Sensor `nastepna_lekcja` przelicza swój stan co minutę lokalnie — **bez dodatkowych zapytań do Librusa**
(dane planu pobierane są razem z resztą, co 2 godziny).

Sensory średnich mają `state_class: measurement` — HA automatycznie rysuje dla nich wykres historyczny po kliknięciu w encję.

Dla nowych instalacji część opcjonalnych sensorów jest **wyłączona domyślnie**,
żeby nie wykonywać niepotrzebnych zapytań: Informacje o uczniu, Szczęśliwy
numerek, Zadania, Średnia ocen, Terminarz oraz legacy sensor Plan lekcji.
Domyślnie aktywne pozostają cztery główne encje: **Oceny, Wiadomości, Następna
lekcja oraz natywny kalendarz Plan lekcji**. Każdą z pozostałych encji można
włączyć w dowolnym momencie w ustawieniach urządzenia/integracji Home Assistant.

### Natywny kalendarz planu lekcji

Encja `calendar.librus_jan_maat_plan_lekcji` korzysta z tego samego cache co sensory planu — **nie wykonuje dodatkowych zapytań do Librusa**. Home Assistant może pobierać z niej wydarzenia dla najbliższych dni. Każda lekcja zachowuje: nazwa, godziny, nauczyciel/sala, status zastępstwa lub odwołania.

- zwykła lekcja ma nazwę przedmiotu,
- zastępstwo ma prefiks `[ZASTĘPSTWO]`,
- odwołana lekcja pozostaje widoczna z prefiksem `[ODWOŁANA]`,
- sala/nauczyciel trafia do lokalizacji wydarzenia,
- odwołana lekcja nie jest wybierana jako bieżące/najbliższe wydarzenie kalendarza.

To pozwala użyć standardowych kart kalendarza HA albo pobrać najbliższe dni do wyświetlenia np. na e-paper.

## 📦 Instalacja

### Opcja 1: HACS (Zalecana)

Kliknij poniższy przycisk, aby automatycznie dodać repozytorium do HACS z właściwą kategorią:

[![Otwórz w HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Misiu&repository=LibrusSynergiaHomeAssistant&category=integration)

Lub ręcznie:

1. Otwórz HACS w Home Assistant
2. Kliknij trzy kropki (⋮) w prawym górnym rogu
3. Wybierz **"Custom repositories"**
4. W polu URL wpisz dokładnie: `https://github.com/Misiu/LibrusSynergiaHomeAssistant`  
   ⚠️ **Bez `.git` na końcu!**
5. W polu **Category** wybierz: **`Integration`**  
   ⚠️ **NIE wybieraj "AppDaemon", "Plugin" ani żadnej innej opcji!**
6. Kliknij **ADD**
7. Znajdź **"Librus Synergia"** na liście i zainstaluj
8. Restartuj Home Assistant

> **Uwaga:** Błąd *"is not a valid app repository"* pojawia się, gdy w kroku 5 zostanie wybrana nieprawidłowa kategoria (np. "AppDaemon"). Upewnij się, że wybrano **Integration**.

### Opcja 2: Instalacja manualna

1. Skopiuj folder `custom_components/librus` do `config/custom_components/`
2. Restartuj Home Assistant
3. Idź do Konfiguracja > Integracje > Dodaj integrację
4. Wyszukaj "Librus Synergia"

## ⚙️ Konfiguracja

1. W Home Assistant: **Konfiguracja** > **Integracje** > **Dodaj integrację**
2. Wyszukaj **"Librus Synergia"**  
3. Podaj swoje dane logowania do Librus Synergia:
   - **Login/Username**: Twój login do Librus
   - **Hasło**: Twoje hasło do Librus
4. Kliknij **"Prześlij"**

### Częstotliwość odświeżania i liczba zapytań

Integracja odpytuje Librusa **co 2 godziny**. Interwał jest ustalony przez
integrację zgodnie z zaleceniami Home Assistanta dla integracji pollingowych
i nie jest konfigurowany w config flow ani opcjach integracji.

Po pierwszym uruchomieniu integracja wykonuje pełny **bootstrap** wszystkich
źródeł. To celowe: pierwszy refresh odbywa się zanim Home Assistant utworzy
platformy i coordinator pozna konteksty aktywnych encji. Dzięki temu setup
pozostaje prosty i przewidywalny.

**Kolejne odświeżenia są context-aware**: coordinator pobiera tylko te źródła
API, które są wymagane przez aktualnie włączone encje. Wyłączenie nieużywanej
encji w Home Assistant zmniejsza więc liczbę kolejnych zapytań bez potrzeby
restartu integracji.

| Encja | Źródło API |
|---|---|
| Informacje o uczniu | `student_info` |
| Szczęśliwy numerek | `student_info` |
| Oceny | `grades` |
| Średnia ocen | `grades` |
| Oceny z przedmiotu | `grades` |
| Średnia z przedmiotu | `grades` |
| Wiadomości | `messages` |
| Zadania | `homework` |
| Terminarz *(domyślnie wyłączony)* | `schedule` |
| Następna lekcja | `timetable` |
| Kalendarz planu lekcji | `timetable` |
| Legacy sensor planu lekcji *(domyślnie wyłączony)* | `timetable + schedule + homework` |

Przykład: jeżeli po bootstrapie zostawisz aktywny wyłącznie
`calendar.librus_jan_maat_plan_lekcji`, kolejne refreshe pobierają tylko
`timetable`. Jeśli włączysz dodatkowo encje ocen, coordinator pobierze
`timetable + grades`.

Legacy `sensor.librus_jan_maat_plan_lekcji` jest dla nowych instalacji
**wyłączony domyślnie**. Zalecanym sposobem korzystania z planu jest natywny
kalendarz Home Assistanta. Sensor legacy pozostaje dostępny ze względu na
kompatybilność ze starszymi dashboardami.

Ręczne odświeżenie działa przez standardową akcję Home Assistanta i korzysta
z tego samego context-aware coordinatora:

```yaml
action: homeassistant.update_entity
target:
  entity_id: calendar.librus_jan_maat_plan_lekcji
```

> `Następna lekcja` oraz legacy `Plan lekcji` przeliczają swój stan
> **co minutę lokalnie**, bez dodatkowych zapytań do Librusa. Zmiana czasu,
> trwającej lekcji czy przejście na kolejny dzień nie uruchamia requestu HTTP.

Po dodaniu integracji encje pojawią się w ciągu kilku sekund. Gotowy dashboard
z planem lekcji wklejasz z pliku
**[`examples/dashboard-plan-lekcji.yaml`](examples/dashboard-plan-lekcji.yaml)** —
instrukcja krok po kroku w sekcji
[Gotowy dashboard](#-gotowy-dashboard--plik-do-wklejenia).

## 🔧 Środowisko testowe

Projekt zawiera local środowisko testowe z Docker:

```bash
# Uruchom środowisko testowe
docker-compose up -d

# Home Assistant dostępny pod: http://localhost:8123
# Code Server dostępny pod: http://localhost:8443 (hasło: homeassistant)
```

## 🛠️ Rozwój

### Wymagania
- Python 3.14.2+
- Home Assistant 2026.9.3+
- librus-apix 1.5.3

### Setup środowiska deweloperskiego
```bash
# Klonuj repozytorium
git clone https://github.com/Misiu/LibrusSynergiaHomeAssistant
cd librus-ha-integration

# Uruchom środowisko testowe
docker-compose up -d

# Edytuj kod w Code Server (http://localhost:8443)
```

### Uruchomienie testów
```bash
python -m pytest -q
```

### Wydawanie nowej wersji

Release jest wykonywany przez GitHub Actions. Po przygotowaniu i zmergowaniu
zmian do `main`:

1. ustaw wersję w `custom_components/librus/manifest.json`,
2. otwórz **Actions → Release → Run workflow**,
3. wybierz gałąź `main`,
4. wpisz wersję, np. `1.1.0`,
5. uruchom workflow.

Workflow sprawdza zgodność podanej wersji z `manifest.json`, uruchamia testy,
Ruff, `compileall`, hassfest i HACS validate. Dopiero po ich powodzeniu tworzy
tag o nazwie wersji (np. `1.1.0`) i publikuje GitHub Release z automatycznie
wygenerowanymi release notes.

Tagu **nie trzeba tworzyć ręcznie**.

## 📝 Logi

Aby włączyć szczegółowe logi, dodaj do `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.librus: debug
```

## ⚠️ Bezpieczeństwo

- **Nie udostępniaj swoich danych logowania.**
- Dane logowania są przechowywane w config entry Home Assistanta; chroń katalog
  konfiguracji oraz kopie zapasowe.
- Diagnostyka integracji usuwa login i hasło przed wygenerowaniem pliku.
- Połączenia z Librus Synergia są wykonywane przez HTTPS.

## 🔎 Diagnostyka

W **Ustawienia → Urządzenia i usługi → Librus Synergia** można pobrać
diagnostykę wpisu integracji. Plik zawiera status coordinatora, dostępność
poszczególnych źródeł i liczniki danych, ale nie zawiera loginu, hasła,
nazwiska ucznia ani treści wiadomości.

## ⚠️ Znane ograniczenia

- Librus jest usługą chmurową bez mechanizmu push, dlatego dane są pobierane
  cyklicznie co 2 godziny.
- Plan lekcji obejmuje bieżący i następny tydzień udostępniony przez Librusa.
- Terminarz obejmuje bieżący i następny miesiąc.
- Integracja celowo nie pobiera pełnej treści wiadomości, aby ich odczyt nie
  oznaczał wiadomości jako przeczytanych.
- Biblioteka `librus-apix` jest synchroniczna, więc wywołania HTTP są
  wykonywane poza pętlą asyncio Home Assistanta.

## 🧰 Rozwiązywanie problemów

1. Jeśli encje są `unavailable`, sprawdź najpierw, czy strona Librus Synergia
   działa i czy nie trwa przerwa techniczna.
2. Jeśli dane logowania zostaną odrzucone, Home Assistant uruchomi reautoryzację
   i poprosi o aktualne hasło.
3. Pobierz diagnostykę integracji i sprawdź pole `data_sources_available`.
4. W razie potrzeby włącz logowanie debug opisane poniżej i dołącz logi do issue,
   po usunięciu danych osobowych.

## 🗑️ Usuwanie integracji

1. Otwórz **Ustawienia → Urządzenia i usługi → Librus Synergia**.
2. Otwórz menu wpisu integracji i wybierz **Usuń**.
3. Jeśli integracja została zainstalowana przez HACS i nie będzie już używana,
   można ją następnie odinstalować również z HACS.
4. Po usunięciu wpisu dane logowania nie są już używane przez integrację.

## 🐛 Zgłaszanie błędów

Jeśli znajdziesz błąd:

1. Włącz logi debug (patrz wyżej)
2. Skopiuj logi z błędem
3. Utwórz issue na GitHub z:
   - Opisem problemu
   - Krokami do reprodukcji
   - Logami (usuń dane osobowe!)

## 📄 Licencja i uznanie autorstwa

Ten projekt jest udostępniany na licencji **MIT** — pełny tekst w pliku
[LICENSE](LICENSE).

### Projekt źródłowy

To repozytorium jest **forkiem** [LukMaverick/LibrusSynergiaHA](https://github.com/LukMaverick/LibrusSynergiaHA)
(licencja MIT). Zgodnie z warunkami MIT oryginalna nota o prawach autorskich
została zachowana w pliku `LICENSE`; nota dotycząca zmian w forku jest dopisana
obok, a nie zamiast niej.

Fork dodaje: plan lekcji, oznaczanie wydarzeń z terminarza i prac domowych
na kartach, kartę nadchodzących wydarzeń oraz natywny kalendarz planu lekcji.

### Komponenty zewnętrzne

Poniższe składniki **nie są dystrybuowane razem z tym repozytorium** — Home
Assistant lub HACS pobierają je osobno. Wymieniamy je dla przejrzystości:

| Komponent | Licencja | Autor | Sposób użycia |
|-----------|----------|-------|----------------|
| [librus-apix](https://github.com/poroknights/librus-apix) | MIT | Pascal Jodłowski | zależność `pip`, deklarowana w `manifest.json` |
| [Mushroom Cards](https://github.com/piitaya/lovelace-mushroom) | Apache-2.0 | piitaya | opcjonalny dodatek frontendu, instalowany z HACS |
| [Home Assistant](https://github.com/home-assistant/core) | Apache-2.0 | Nabu Casa i społeczność | środowisko uruchomieniowe integracji |

Integracja komunikuje się z systemem **Librus Synergia**. Projekt nie jest
powiązany z firmą Librus ani przez nią wspierany; nazwa użyta wyłącznie
w celach identyfikacyjnych.

## 🤝 Wkład

Pull requesty są mile widziane — zgłoś je przez
[Issues](https://github.com/Misiu/LibrusSynergiaHomeAssistant/issues) lub bezpośrednio
jako PR.

### 🙏 Podziękowania

Specjalne podziękowania dla **KB** za wsparcie i pomoc w rozwoju projektu.

## 👨‍💻 Autor

**[Misiu](https://github.com/Misiu)**

Stworzono na bazie biblioteki [librus-apix](https://github.com/poroknights/librus-apix)

---

**⭐ Jeśli podoba Ci się projekt, zostaw gwiazdkę na GitHub!**

