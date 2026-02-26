"""DataUpdateCoordinator for KodaxHA cameras."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any
from urllib.parse import unquote_plus

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, CMD_GET_CAMINFO, CMD_GET_TEMP_HUMID

_LOGGER = logging.getLogger(__name__)


def _parse_camera_response(body: str, command: str) -> dict[str, str] | None:
    """Parse the flat key=value response returned by the camera.

    Expected format:  ``get_caminfo: key1=val1&key2=val2&...``
    """
    body = body.strip()
    if not body.startswith(command):
        return None

    # Strip the command prefix ("get_caminfo: ")
    prefix = command + ": "
    if prefix not in body:
        return None

    query_string = body.split(prefix, 1)[1].rstrip("&")
    if not query_string or query_string == "-1":
        return None

    result: dict[str, str] = {}
    for pair in query_string.split("&"):
        if "=" in pair:
            k, _, v = pair.partition("=")
            result[k.strip()] = unquote_plus(v.strip())

    return result or None


class KodaxHACoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls a single Kodak camera and exposes its state to all entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        camera_ip: str,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"KodaxHA {camera_ip}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.camera_ip = camera_ip
        self.base_url = f"http://{camera_ip}/"
        self._session = async_get_clientsession(hass)

    # ── Public helpers ──────────────────────────────────────────────────────

    async def async_send_command(
        self,
        command: str,
        params: dict[str, Any] | None = None,
    ) -> bool:
        """Fire a command at the camera and return True on success."""
        url = self.base_url + "?req=" + command
        if params:
            for key, value in params.items():
                url += f"&{key}={value}"

        _LOGGER.debug("Sending camera command: %s", url)
        try:
            async with asyncio.timeout(10):
                async with self._session.get(
                    url, timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    success = resp.status == 200
                    if not success:
                        _LOGGER.warning(
                            "Camera returned HTTP %d for command %s",
                            resp.status,
                            command,
                        )
                    return success
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Failed to send command %s: %s", command, err)
            return False

    # ── Internal polling ────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the latest state from the camera."""
        try:
            async with asyncio.timeout(15):
                data: dict[str, Any] = {}

                # Primary info — always fetched
                caminfo = await self._fetch_command(CMD_GET_CAMINFO)
                if caminfo:
                    data.update(caminfo)
                else:
                    raise UpdateFailed(
                        f"Camera at {self.camera_ip} did not respond to get_caminfo"
                    )

                # Temperature / humidity — only if the sensor is present
                # (the camera returns -273 / -1 when there is no sensor)
                temp_str = data.get("tem", "-273")
                hum_str = data.get("hum", "-1")
                has_env_sensor = (
                    _safe_float(temp_str, -273.0) > -273.0
                    or _safe_float(hum_str, -1.0) > -1.0
                )
                if has_env_sensor:
                    temp_hum = await self._fetch_command(CMD_GET_TEMP_HUMID)
                    if temp_hum:
                        data.update(temp_hum)

                return data

        except UpdateFailed:
            raise
        except aiohttp.ClientError as err:
            raise UpdateFailed(
                f"Network error communicating with {self.camera_ip}: {err}"
            ) from err
        except TimeoutError as err:
            raise UpdateFailed(
                f"Timeout communicating with {self.camera_ip}"
            ) from err

    async def _fetch_command(self, command: str) -> dict[str, str] | None:
        """GET a camera endpoint and parse the response."""
        url = self.base_url + "?req=" + command
        try:
            async with self._session.get(
                url, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning(
                        "Camera returned HTTP %d for %s", resp.status, command
                    )
                    return None
                body = await resp.text()
                return _parse_camera_response(body, command)
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.warning("Error fetching %s: %s", command, err)
            return None


def _safe_float(value: str | None, default: float = 0.0) -> float:
    """Parse a float without raising."""
    try:
        return float(value or default)
    except (ValueError, TypeError):
        return default
