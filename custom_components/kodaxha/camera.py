"""Camera platform for KodaxHA cameras.

Provides a HA Camera entity that:
  - Fetches JPEG snapshots from a configurable URL (snapshot_url option)
  - Exposes an RTSP stream URL (stream_url option) so HA can proxy the stream
    and Homebridge / HomeKit can consume it via homebridge-homeassistant or
    homebridge-camera-ffmpeg.

Both URLs are optional and can be set/changed any time via the integration's
"Configure" button in Settings → Integrations — no re-add needed.

Finding your RTSP URL:
  Many Kodak cameras expose RTSP at rtsp://<ip>:554/ or similar.
  Use VLC (Media → Open Network Stream) to probe common paths:
    rtsp://<ip>/
    rtsp://<ip>:554/
    rtsp://<ip>/live
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp
from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CAMERA_IP, CONF_SNAPSHOT_URL, CONF_STREAM_URL, DOMAIN
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

    # Options take precedence over data so users can update without re-adding
    stream_url: str | None = (
        entry.options.get(CONF_STREAM_URL) or entry.data.get(CONF_STREAM_URL)
    ) or None
    snapshot_url: str | None = (
        entry.options.get(CONF_SNAPSHOT_URL) or entry.data.get(CONF_SNAPSHOT_URL)
    ) or None

    async_add_entities([KodaxHACamera(coordinator, camera_ip, stream_url, snapshot_url)])


class KodaxHACamera(CoordinatorEntity[KodaxHACoordinator], Camera):
    """Camera entity that exposes snapshots and an optional RTSP stream."""

    _attr_has_entity_name = True
    _attr_name = "Live View"

    def __init__(
        self,
        coordinator: KodaxHACoordinator,
        camera_ip: str,
        stream_url: str | None,
        snapshot_url: str | None,
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._camera_ip = camera_ip
        self._stream_url = stream_url
        self._snapshot_url = snapshot_url
        self._attr_unique_id = f"kodaxha_{camera_ip.replace('.', '_')}_camera"
        self._attr_device_info = _device_info(camera_ip)

        if stream_url:
            self._attr_supported_features = CameraEntityFeature.STREAM

    # ── HA Camera interface ─────────────────────────────────────────────────

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return a JPEG snapshot.

        If snapshot_url is not configured, returns None (camera shows
        as unavailable in Lovelace but control entities still work).
        """
        if not self._snapshot_url:
            return None

        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(10):
                async with session.get(
                    self._snapshot_url,
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    _LOGGER.warning(
                        "Snapshot fetch returned HTTP %d from %s",
                        resp.status,
                        self._snapshot_url,
                    )
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Snapshot fetch failed: %s", err)

        return None

    async def stream_source(self) -> str | None:
        """Return the RTSP URL for HA stream proxy (used by Homebridge too)."""
        return self._stream_url
