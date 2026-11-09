from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import PRICES


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(Price(entry.runtime_data, key) for key in PRICES)


class Price(CoordinatorEntity, SensorEntity):
    """The price of the current 15-minute slot, with all known slots in the `prices` attribute."""

    _attr_has_entity_name = True  # name, and so the entity id, in the system's language (translations/)
    _attr_native_unit_of_measurement = "CHF/kWh"
    _attr_suggested_display_precision = 4
    _unrecorded_attributes = frozenset({"prices"})  # ~200 slots, too large for the recorder

    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"

    @property
    def available(self) -> bool:
        # Prices fetched before a failed refresh stay valid until their slot ends.
        return self.native_value is not None

    @property
    def native_value(self) -> float | None:
        now = dt_util.utcnow()
        return next((s[self._key] for s in self.coordinator.data if s["start"] <= now < s["end"]), None)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "prices": [
                {"start": s["start"], "end": s["end"], "price": s[self._key]} for s in self.coordinator.data
            ]
        }
