"""Tests for Librus APIX diagnostics."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.librus_apix.const import DOMAIN
from custom_components.librus_apix.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redacts_credentials_and_returns_counts(
    hass: HomeAssistant,
) -> None:
    """Diagnostics expose useful counts without personal school data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Librus",
        data={CONF_USERNAME: "123456", CONF_PASSWORD: "top-secret"},
    )
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.update_interval.total_seconds.return_value = 7200
    coordinator.data = {
        "student_info": SimpleNamespace(name="Jan Kowalski"),
        "oceny": [{"grade": "5"}],
        "oceny_wg_przedmiotu": {"Matematyka": [{"ocena": "5"}]},
        "wiadomosci": [{"title": "Private message"}],
        "zadania": [{"przedmiot": "Matematyka"}],
        "terminarz": [{"tytul": "Sprawdzian"}],
        "plan_lekcji": [{"przedmiot": "Fizyka"}, {"przedmiot": "Historia"}],
        "semestr_biezacy": 1,
    }
    entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(hass, entry)

    serialized = str(result)
    assert "123456" not in serialized
    assert "top-secret" not in serialized
    assert "Jan Kowalski" not in serialized
    assert "Private message" not in serialized
    assert result["coordinator"]["grade_count"] == 1
    assert result["coordinator"]["subject_count"] == 1
    assert result["coordinator"]["lesson_count"] == 2
    assert result["coordinator"]["update_interval_seconds"] == 7200
