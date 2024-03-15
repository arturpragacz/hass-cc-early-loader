"""Hacking persistent_notification for early loading hook."""

import asyncio
import logging
import voluptuous as vol

from homeassistant.bootstrap import CORE_INTEGRATIONS
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import (
    DATA_COMPONENTS,
    DATA_CUSTOM_COMPONENTS,
    DATA_INTEGRATIONS,
    DATA_MISSING_PLATFORMS
)
from homeassistant.setup import async_setup_component, _async_setup_component


_LOGGER = logging.getLogger("early_loader")

DOMAIN = "persistent_notification"

def schema_validator(remove_extra=False):
    def validate(schema: dict):
        new_schema = {}
        for k, v in schema.items():
            if not isinstance(v, dict):
                continue
            hook = v.get("early_loader_hook", False)
            if cv.boolean(hook):
                new_schema[k] = v
        return new_schema if remove_extra else schema

    return validate

CONFIG_SCHEMA = vol.Schema(schema_validator())


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    if DOMAIN not in CORE_INTEGRATIONS:
        _LOGGER.error("DOMAIN no longer in CORE_INTEGRATIONS: early loading not executed")
    result = await async_setup_builtin_self(hass, config)
    await async_setup_others(hass, config)
    return result

async def async_setup_others(hass: HomeAssistant, config: ConfigType) -> None:
    DOMAINS_SCHEMA = vol.Schema(schema_validator(True))
    domains = DOMAINS_SCHEMA(config)
    if not domains:
        return

    tasks = {
        hass.loop.create_task(async_setup_component(hass, domain, config))
        for domain in domains
        if domain not in hass.config.components
    }
    # async_freeze has to match async_timeout in homeassistant.setup._async_setup_component
    async with hass.timeout.async_freeze(DOMAIN):
        await asyncio.gather(*tasks, return_exceptions=True)

async def async_setup_builtin_self(hass: HomeAssistant, config: ConfigType) -> bool:
    """
    Setup builtin integration.
    Has to be compatible with the workings of
    homeassistant.setup.{async_setup_component,_async_setup_component}.
    """
    clear_caches_and_delete_custom_self(hass, DOMAIN)
    return await _async_setup_component(hass, DOMAIN, config)

def clear_caches_and_delete_custom_self(hass: HomeAssistant, domain: str) -> None:
    """
    Clear caches.
    Look at:
    - homeassistant.loader.async_get_integrations
    - homeassistant.loader.async_get_custom_components
    - homeassistant.loader.Integration.get_component
    """
    integration_cache = hass.data[DATA_INTEGRATIONS]
    integration_cache.pop(domain, None)
    custom_integration_cache = hass.data[DATA_CUSTOM_COMPONENTS]
    custom_integration_cache.pop(domain, None)
    component_cache = hass.data[DATA_COMPONENTS]
    component_cache.pop(domain, None)
    missing_platforms_cache = hass.data[DATA_MISSING_PLATFORMS]
    missing_platforms_cache.clear()
