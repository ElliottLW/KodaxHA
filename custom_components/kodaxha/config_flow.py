"""Config flow for the KodaxHA integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import unquote_plus

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_CAMERA_IP,
    CONF_LOCAL_IP,
    CONF_SCAN_INTERVAL,
    CONF_SNAPSHOT_URL,
    CONF_STREAM_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CAMERA_IP): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            int, vol.Range(min=10, max=300)
        ),
    }
)


async def _validate_camera(hass: HomeAssistant, camera_ip: str) -> dict[str, str]:
    """Hit get_caminfo and confirm the response looks like a Kodak camera.

    Returns a dict with ``title`` (used as the config-entry title) plus any
    useful meta parsed from the response.  Raises ``ValueError`` with a
    translation key on failure.
    """
    session = async_get_clientsession(hass)
    url = f"http://{camera_ip}/?req=get_caminfo"

    try:
        async with asyncio.timeout(10):
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    raise ValueError("cannot_connect")
                body = await resp.text()
    except (aiohttp.ClientConnectionError, aiohttp.ClientError):
        raise ValueError("cannot_connect")
    except TimeoutError:
        raise ValueError("timeout")

    if not body.strip().startswith("get_caminfo"):
        raise ValueError("not_kodak_camera")

    # Parse just enough to build a nice title
    info: dict[str, str] = {}
    try:
        qs = body.split("get_caminfo: ", 1)[1].rstrip("&")
        for pair in qs.split("&"):
            if "=" in pair:
                k, _, v = pair.partition("=")
                info[k.strip()] = unquote_plus(v.strip())
    except (IndexError, ValueError):
        pass  # non-critical — we already confirmed it's a Kodak cam

    ssid = info.get("ssid3") or info.get("ssid1") or ""
    hw_id = info.get("hw_id", "")
    ip_clean = camera_ip.replace(".", "_")

    title_parts = [f"Kodak Camera ({camera_ip})"]
    if ssid:
        title_parts.append(f"on {ssid}")

    return {
        "title": " ".join(title_parts),
        "hw_id": hw_id,
        "unique_suffix": ip_clean,
    }


class KodaxHAConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for KodaxHA."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "KodaxHAOptionsFlow":
        return KodaxHAOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step where the user enters the camera IP."""
        errors: dict[str, str] = {}

        if user_input is not None:
            camera_ip = user_input[CONF_CAMERA_IP].strip()

            try:
                meta = await _validate_camera(self.hass, camera_ip)
            except ValueError as err:
                errors["base"] = str(err)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating camera %s", camera_ip)
                errors["base"] = "unknown"
            else:
                unique_id = f"kodaxha_{meta['unique_suffix']}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=meta["title"],
                    data={
                        CONF_CAMERA_IP: camera_ip,
                        CONF_SCAN_INTERVAL: user_input.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )


# ── Options flow (stream / snapshot URLs) ───────────────────────────────────


class KodaxHAOptionsFlow(config_entries.OptionsFlow):
    """Let the user add/change stream and snapshot URLs without re-adding."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            # Strip blank strings → None so they don't override camera.py logic
            clean = {k: v.strip() for k, v in user_input.items() if isinstance(v, str)}
            return self.async_create_entry(title="", data=clean)

        current = self._config_entry.options

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_STREAM_URL,
                    description={
                        "suggested_value": current.get(CONF_STREAM_URL, "")
                    },
                ): str,
                vol.Optional(
                    CONF_SNAPSHOT_URL,
                    description={
                        "suggested_value": current.get(CONF_SNAPSHOT_URL, "")
                    },
                ): str,
                vol.Optional(
                    CONF_LOCAL_IP,
                    description={
                        "suggested_value": current.get(CONF_LOCAL_IP, "")
                    },
                ): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=current.get(
                        CONF_SCAN_INTERVAL,
                        self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ),
                ): vol.All(int, vol.Range(min=10, max=300)),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
