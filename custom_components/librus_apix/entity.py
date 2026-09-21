"""Base entities for the Librus APIX integration."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LibrusConfigEntry, LibrusDataUpdateCoordinator


class LibrusEntity(CoordinatorEntity[LibrusDataUpdateCoordinator]):
    """Base class for Librus entities."""

    _attr_has_entity_name = True
    _availability_key: str | None = None

    def __init__(
        self,
        coordinator: LibrusDataUpdateCoordinator,
        config_entry: LibrusConfigEntry,
    ) -> None:
        """Initialize a Librus entity."""
        super().__init__(coordinator)
        student_info = coordinator.data["student_info"]
        student_name = student_info.name if student_info else "Librus"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=f"Librus - {student_name}",
            manufacturer="Librus",
            model="Synergia",
        )


    @property
    def available(self) -> bool:
        """Return whether the data source for this entity is available."""
        if not super().available or self._availability_key is None:
            return super().available
        availability = self.coordinator.data.get("availability", {})
        return availability.get(self._availability_key, True)
