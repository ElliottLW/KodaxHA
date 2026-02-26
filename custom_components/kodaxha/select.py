"""Select platform for KodaxHA cameras."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CAMERA_IP,
    DOMAIN,
    FLIP_OPTIONS,
    FLIP_VALUES,
    NIGHT_VISION_OPTIONS,
    NIGHT_VISION_VALUES,
    RESOLUTION_OPTIONS,
    RESOLUTION_VALUES,
    SENSITIVITY_OPTIONS,
    SENSITIVITY_VALUES,
)
from .coordinator import KodaxHACoordinator
from .sensor import _device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KodaxHACoordinator = hass.data[DOMAIN][entry.entry_id]
    camera_ip: str = entry.data[CONF_CAMERA_IP]

    async_add_entities(
        [
            KodaxHANightVisionSelect(coordinator, camera_ip),
            KodaxHAResolutionSelect(coordinator, camera_ip),
            KodaxHAMotionSensitivitySelect(coordinator, camera_ip),
            KodaxHAOrientationSelect(coordinator, camera_ip),
        ]
    )


# ── Base class ──────────────────────────────────────────────────────────────

class _KodaxHASelectBase(CoordinatorEntity[KodaxHACoordinator], SelectEntity):
    """Shared behaviour for all KodaxHA select entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KodaxHACoordinator, camera_ip: str) -> None:
        super().__init__(coordinator)
        self._camera_ip = camera_ip
        self._attr_device_info = _device_info(camera_ip)


# ── Night vision ────────────────────────────────────────────────────────────

class KodaxHANightVisionSelect(_KodaxHASelectBase):
    _attr_name = "Night Vision"
    _attr_icon = "mdi:weather-night"
    _attr_options = list(NIGHT_VISION_OPTIONS)

    def __init__(self, coordinator: KodaxHACoordinator, camera_ip: str) -> None:
        super().__init__(coordinator, camera_ip)
        self._attr_unique_id = f"kodaxha_{camera_ip.replace('.', '_')}_night_vision"

    @property
    def current_option(self) -> str | None:
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.get("ir")
        if raw is None:
            return None
        return NIGHT_VISION_VALUES.get(int(raw))

    async def async_select_option(self, option: str) -> None:
        value = NIGHT_VISION_OPTIONS.get(option)
        if value is not None:
            await self.coordinator.async_send_command(
                "set_night_vision", {"value": value}
            )
            await self.coordinator.async_request_refresh()


# ── Video resolution ────────────────────────────────────────────────────────

class KodaxHAResolutionSelect(_KodaxHASelectBase):
    _attr_name = "Video Resolution"
    _attr_icon = "mdi:video-high-definition"
    _attr_options = list(RESOLUTION_OPTIONS)

    def __init__(self, coordinator: KodaxHACoordinator, camera_ip: str) -> None:
        super().__init__(coordinator, camera_ip)
        self._attr_unique_id = f"kodaxha_{camera_ip.replace('.', '_')}_resolution"

    @property
    def current_option(self) -> str | None:
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.get("res")
        if raw is None:
            return None
        return RESOLUTION_VALUES.get(int(raw))

    async def async_select_option(self, option: str) -> None:
        value = RESOLUTION_OPTIONS.get(option)
        if value is not None:
            await self.coordinator.async_send_command(
                "set_resolution", {"value": value}
            )
            await self.coordinator.async_request_refresh()


# ── Motion sensitivity ──────────────────────────────────────────────────────

class KodaxHAMotionSensitivitySelect(_KodaxHASelectBase):
    _attr_name = "Motion Sensitivity"
    _attr_icon = "mdi:tune"
    _attr_options = list(SENSITIVITY_OPTIONS)

    def __init__(self, coordinator: KodaxHACoordinator, camera_ip: str) -> None:
        super().__init__(coordinator, camera_ip)
        self._attr_unique_id = (
            f"kodaxha_{camera_ip.replace('.', '_')}_motion_sensitivity"
        )

    @property
    def current_option(self) -> str | None:
        if not self.coordinator.data:
            return None
        # md format:  "enabled:schedule:sensitivity:unknown"  e.g. "1:0:3:0"
        md = self.coordinator.data.get("md", "")
        parts = md.split(":")
        if len(parts) >= 3:
            try:
                return SENSITIVITY_VALUES.get(int(parts[2]))
            except (ValueError, IndexError):
                pass
        return None

    async def async_select_option(self, option: str) -> None:
        value = SENSITIVITY_OPTIONS.get(option)
        if value is not None:
            await self.coordinator.async_send_command(
                "set_motion_sensitivity", {"value": value}
            )
            await self.coordinator.async_request_refresh()


# ── Camera orientation ──────────────────────────────────────────────────────

class KodaxHAOrientationSelect(_KodaxHASelectBase):
    _attr_name = "Camera Orientation"
    _attr_icon = "mdi:rotate-3d-variant"
    _attr_options = list(FLIP_OPTIONS)

    def __init__(self, coordinator: KodaxHACoordinator, camera_ip: str) -> None:
        super().__init__(coordinator, camera_ip)
        self._attr_unique_id = (
            f"kodaxha_{camera_ip.replace('.', '_')}_orientation"
        )

    @property
    def current_option(self) -> str | None:
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.get("flipup")
        if raw is None:
            return None
        return FLIP_VALUES.get(int(raw))

    async def async_select_option(self, option: str) -> None:
        value = FLIP_OPTIONS.get(option)
        if value is not None:
            await self.coordinator.async_send_command(
                "set_flipup", {"value": value}
            )
            await self.coordinator.async_request_refresh()
