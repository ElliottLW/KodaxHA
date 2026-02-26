"""The KodaxHA integration."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CARD_URL,
    CONF_CAMERA_IP,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import KodaxHACoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.CAMERA,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Kodak camera from a config entry."""
    camera_ip: str = entry.data[CONF_CAMERA_IP]
    scan_interval: int = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    coordinator = KodaxHACoordinator(hass, camera_ip, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the Lovelace card as a static resource.  Runs once per HA
    # start; subsequent calls are silently ignored by HA's dedup logic.
    await _async_register_card(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


# ── Frontend card registration ───────────────────────────────────────────────

async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve kodaxha-card.js and auto-add it as a Lovelace module resource."""
    card_path = Path(__file__).parent / "www" / "kodaxha-card.js"
    if not card_path.exists():
        _LOGGER.warning("KodaxHA: card file not found at %s", card_path)
        return

    # ── Serve the file over HTTP ──────────────────────────────────────────
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(card_path), cache_headers=False)]
        )
    except (ImportError, TypeError):
        # Fallback for HA < 2024.4
        try:
            hass.http.register_static_path(CARD_URL, str(card_path), cache_headers=False)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("KodaxHA: could not serve card JS: %s", err)
            return
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("KodaxHA: could not serve card JS: %s", err)
        return

    # ── Auto-add to Lovelace resources (storage mode only) ────────────────
    try:
        lovelace = hass.data.get("lovelace") or {}
        resources = lovelace.get("resources")
        if resources is not None and hasattr(resources, "async_items"):
            existing = {item.get("url") for item in resources.async_items()}
            if CARD_URL not in existing:
                await resources.async_create_item(
                    {"res_type": "module", "url": CARD_URL}
                )
                _LOGGER.info("KodaxHA: registered card as Lovelace resource → %s", CARD_URL)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug(
            "KodaxHA: auto-Lovelace-resource skipped (YAML mode or older HA). "
            "Manually add %s as a module resource if needed. (%s)",
            CARD_URL,
            err,
        )

