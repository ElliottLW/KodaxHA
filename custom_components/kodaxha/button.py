"""Button platform for KodaxHA cameras."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CAMERA_IP, DOMAIN
from .coordinator import KodaxHACoordinator
from .sensor import _device_info

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=False)
class KodaxHAButtonDescription(ButtonEntityDescription):
    key: str = ""
    command: str = ""
    params: dict[str, Any] | None = None


BUTTON_DESCRIPTIONS: tuple[KodaxHAButtonDescription, ...] = (
    # ── System ─────────────────────────────────────────────────────────────
    KodaxHAButtonDescription(
        key="restart",
        name="Restart Camera",
        icon="mdi:restart",
        command="restart_system",
    ),
    # ── Melody playback ────────────────────────────────────────────────────
    KodaxHAButtonDescription(
        key="melody_stop",
        name="Stop Melody",
        icon="mdi:stop-circle",
        command="melodystop",
    ),
    KodaxHAButtonDescription(
        key="melody1",
        name="Play Melody 1",
        icon="mdi:music-note",
        command="melody1",
        params={"duration": 2},  # 10 seconds
    ),
    KodaxHAButtonDescription(
        key="melody2",
        name="Play Melody 2",
        icon="mdi:music-note",
        command="melody2",
        params={"duration": 2},
    ),
    KodaxHAButtonDescription(
        key="melody3",
        name="Play Melody 3",
        icon="mdi:music-note",
        command="melody3",
        params={"duration": 2},
    ),
    KodaxHAButtonDescription(
        key="melody4",
        name="Play Melody 4",
        icon="mdi:music-note",
        command="melody4",
        params={"duration": 2},
    ),
    KodaxHAButtonDescription(
        key="melody5",
        name="Play Melody 5",
        icon="mdi:music-note",
        command="melody5",
        params={"duration": 2},
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
        KodaxHAButtonEntity(coordinator, desc, camera_ip)
        for desc in BUTTON_DESCRIPTIONS
    )


class KodaxHAButtonEntity(CoordinatorEntity[KodaxHACoordinator], ButtonEntity):
    """A press-only action backed by the KodaxHA coordinator."""

    entity_description: KodaxHAButtonDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KodaxHACoordinator,
        description: KodaxHAButtonDescription,
        camera_ip: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"kodaxha_{camera_ip.replace('.', '_')}_{description.key}"
        )
        self._attr_device_info = _device_info(camera_ip)

    async def async_press(self) -> None:
        success = await self.coordinator.async_send_command(
            self.entity_description.command,
            self.entity_description.params,
        )
        if not success:
            _LOGGER.warning(
                "Command %s failed for camera %s",
                self.entity_description.command,
                self.coordinator.camera_ip,
            )
