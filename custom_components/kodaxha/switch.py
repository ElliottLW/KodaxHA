"""Switch platform for KodaxHA cameras."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CAMERA_IP, DOMAIN
from .coordinator import KodaxHACoordinator
from .sensor import _device_info

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=False)
class KodaxHASwitchDescription(SwitchEntityDescription):
    key: str = ""
    is_on_fn: Callable[[dict[str, Any]], bool] | None = None
    turn_on_command: str = ""
    turn_on_params: dict[str, Any] | None = None
    turn_off_command: str = ""
    turn_off_params: dict[str, Any] | None = None


def _md_is_on(data: dict) -> bool:
    """Motion detection is active when the first colon-separated part is '1'."""
    return data.get("md", "0:0:3:0").split(":")[0] == "1"


def _sd_is_on(data: dict) -> bool:
    """Sound detection is active when the first colon-separated part is '1'."""
    return data.get("sd", "0:2:3:0").split(":")[0] == "1"


SWITCH_DESCRIPTIONS: tuple[KodaxHASwitchDescription, ...] = (
    KodaxHASwitchDescription(
        key="motion_detection",
        name="Motion Detection",
        icon="mdi:motion-sensor",
        is_on_fn=_md_is_on,
        turn_on_command="set_motion_source",
        turn_on_params={"value": 1, "schedule": 0},
        turn_off_command="set_motion_source",
        turn_off_params={"value": 0, "schedule": 0},
    ),
    KodaxHASwitchDescription(
        key="sound_detection",
        name="Sound Detection",
        icon="mdi:microphone",
        is_on_fn=_sd_is_on,
        # Enable with medium sensitivity; sensitivity is preserved if already set
        turn_on_command="set_sound_detection",
        turn_on_params={"value": 1, "sensitivity": 3, "schedule": 0},
        turn_off_command="set_sound_detection",
        turn_off_params={"value": 0, "sensitivity": 3, "schedule": 0},
    ),
    KodaxHASwitchDescription(
        key="blue_led",
        name="Blue LED",
        icon="mdi:led-on",
        is_on_fn=lambda d: d.get("blue_led_en") == "1",
        turn_on_command="set_blue_led",
        turn_on_params={"enable": 1, "on_time": 180, "red_led_affect": 0},
        turn_off_command="set_blue_led",
        turn_off_params={"enable": 0, "on_time": 180, "red_led_affect": 0},
    ),
    KodaxHASwitchDescription(
        key="sdatrm",
        name="Auto-Remove Old Clips",
        icon="mdi:delete-clock",
        is_on_fn=lambda d: d.get("sdatrm") == "1",
        turn_on_command="auto_rm_clip",
        turn_on_params={"value": 1, "clips": 10},
        turn_off_command="auto_rm_clip",
        turn_off_params={"value": 0, "clips": 10},
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
        KodaxHASwitchEntity(coordinator, desc, camera_ip)
        for desc in SWITCH_DESCRIPTIONS
    )


class KodaxHASwitchEntity(CoordinatorEntity[KodaxHACoordinator], SwitchEntity):
    """A toggleable switch backed by the KodaxHA coordinator."""

    entity_description: KodaxHASwitchDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KodaxHACoordinator,
        description: KodaxHASwitchDescription,
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

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command(
            self.entity_description.turn_on_command,
            self.entity_description.turn_on_params,
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send_command(
            self.entity_description.turn_off_command,
            self.entity_description.turn_off_params,
        )
        await self.coordinator.async_request_refresh()
