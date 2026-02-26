"""Sensor platform for KodaxHA cameras."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CAMERA_IP, DOMAIN
from .coordinator import KodaxHACoordinator, _safe_float


@dataclass(frozen=False)
class KodaxHASensorDescription(SensorEntityDescription):
    """Extended description with availability / value callbacks."""

    # override key so dataclass doesn't complain it has no default
    key: str = ""
    value_fn: Callable[[str], Any] | None = None
    available_fn: Callable[[dict[str, Any]], bool] | None = None


def _md_available(data: dict) -> bool:
    """Motion detection availability — only False if the camera sends nothing."""
    return data.get("md") is not None


SENSOR_DESCRIPTIONS: tuple[KodaxHASensorDescription, ...] = (
    # ── Battery ────────────────────────────────────────────────────────────
    KodaxHASensorDescription(
        key="bat",
        name="Battery Level",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
    ),
    # ── Network ────────────────────────────────────────────────────────────
    # Camera reports WiFi as 0-100 % (not dBm), so no device_class to avoid
    # HA's unit validation error for signal_strength (which expects dBm/dB).
    KodaxHASensorDescription(
        key="wifi",
        name="WiFi Signal",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        icon="mdi:wifi",
    ),
    # ── Environment ────────────────────────────────────────────────────────
    KodaxHASensorDescription(
        key="tem_float",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        available_fn=lambda d: _safe_float(d.get("tem_float"), -273.0) > -273.0,
    ),
    KodaxHASensorDescription(
        key="hum_float",
        name="Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        available_fn=lambda d: _safe_float(d.get("hum_float"), -1.0) > -1.0,
    ),
    # ── Storage ────────────────────────────────────────────────────────────
    KodaxHASensorDescription(
        key="sdcap",
        name="SD Card Capacity",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="MB",
        icon="mdi:sd",
        available_fn=lambda d: int(d.get("sdcap", -1)) > 0,
        value_fn=lambda v: abs(int(v)),
    ),
    KodaxHASensorDescription(
        key="sdfree",
        name="SD Card Free Space",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="MB",
        icon="mdi:sd",
        available_fn=lambda d: int(d.get("sdcap", -1)) > 0,
        value_fn=lambda v: int(v),
    ),
    # ── Video ──────────────────────────────────────────────────────────────
    KodaxHASensorDescription(
        key="brate",
        name="Video Bitrate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kbps",
        icon="mdi:video",
        suggested_display_precision=0,
        value_fn=lambda v: int(v),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KodaxHA sensor entities."""
    coordinator: KodaxHACoordinator = hass.data[DOMAIN][entry.entry_id]
    camera_ip: str = entry.data[CONF_CAMERA_IP]

    async_add_entities(
        KodaxHASensorEntity(coordinator, desc, camera_ip)
        for desc in SENSOR_DESCRIPTIONS
    )


class KodaxHASensorEntity(CoordinatorEntity[KodaxHACoordinator], SensorEntity):
    """A single sensor backed by the KodaxHA coordinator."""

    entity_description: KodaxHASensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KodaxHACoordinator,
        description: KodaxHASensorDescription,
        camera_ip: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"kodaxha_{camera_ip.replace('.', '_')}_{description.key}"
        )
        self._attr_device_info = _device_info(camera_ip)

    @property
    def native_value(self) -> float | int | str | None:
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.get(self.entity_description.key)
        if raw is None:
            return None
        if self.entity_description.value_fn:
            try:
                return self.entity_description.value_fn(raw)
            except (ValueError, TypeError):
                return None
        # Default: try numeric, fall back to string
        try:
            return float(raw)
        except (ValueError, TypeError):
            return raw

    @property
    def available(self) -> bool:
        if not super().available or not self.coordinator.data:
            return False
        fn = self.entity_description.available_fn
        if fn:
            try:
                return fn(self.coordinator.data)
            except (ValueError, TypeError, KeyError):
                return False
        return self.coordinator.data.get(self.entity_description.key) is not None


# ── Shared helper ───────────────────────────────────────────────────────────

def _device_info(camera_ip: str) -> dict:
    return {
        "identifiers": {(DOMAIN, camera_ip)},
        "name": f"Kodak Camera ({camera_ip})",
        "manufacturer": "Kodak",
        "model": "Smart Home Camera",
        "configuration_url": f"http://{camera_ip}/",
    }
