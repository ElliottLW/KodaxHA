"""Binary sensor platform for KodaxHA cameras."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CAMERA_IP, DOMAIN
from .coordinator import KodaxHACoordinator
from .sensor import _device_info


@dataclass(frozen=False)
class KodaxHABinarySensorDescription(BinarySensorEntityDescription):
    key: str = ""
    is_on_fn: Callable[[dict[str, Any]], bool] | None = None


BINARY_SENSOR_DESCRIPTIONS: tuple[KodaxHABinarySensorDescription, ...] = (
    KodaxHABinarySensorDescription(
        key="charge",
        name="Charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        is_on_fn=lambda d: d.get("charge") == "1",
    ),
    KodaxHABinarySensorDescription(
        key="mvr",
        name="Motion Recording",
        device_class=BinarySensorDeviceClass.MOTION,
        icon="mdi:record-circle",
        is_on_fn=lambda d: d.get("mvr") == "1",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KodaxHACoordinator = hass.data[DOMAIN][entry.entry_id]
    camera_ip: str = entry.data[CONF_CAMERA_IP]

    async_add_entities(
        KodaxHABinarySensorEntity(coordinator, desc, camera_ip)
        for desc in BINARY_SENSOR_DESCRIPTIONS
    )


class KodaxHABinarySensorEntity(CoordinatorEntity[KodaxHACoordinator], BinarySensorEntity):
    """A binary sensor backed by the KodaxHA coordinator."""

    entity_description: KodaxHABinarySensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KodaxHACoordinator,
        description: KodaxHABinarySensorDescription,
        camera_ip: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"kodaxha_{camera_ip.replace('.', '_')}_{description.key}"
        )
        self._attr_device_info = _device_info(camera_ip)

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        try:
            return self.entity_description.is_on_fn(self.coordinator.data)  # type: ignore[misc]
        except (ValueError, TypeError, KeyError):
            return None
