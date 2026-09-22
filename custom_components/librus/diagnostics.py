"""Diagnostics support for the Librus Synergia integration."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import LibrusConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LibrusConfigEntry
) -> dict[str, Any]:
    """Return privacy-safe diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data

    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "student_info_available": data["student_info"] is not None,
            "grade_count": len(data["oceny"]),
            "subject_count": len(data["oceny_wg_przedmiotu"]),
            "message_count": len(data["wiadomosci"]),
            "homework_count": len(data["zadania"]),
            "schedule_count": len(data["terminarz"]),
            "lesson_count": len(data["plan_lekcji"]),
            "current_semester": data["semestr_biezacy"],
            "data_sources_available": data.get("availability", {}),
        },
    }
