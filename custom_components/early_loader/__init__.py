"""Early Loader component."""

import asyncio
from collections.abc import Collection
import logging
from pathlib import Path
import shutil
from typing import Any, cast

import voluptuous as vol

from homeassistant.bootstrap import CORE_INTEGRATIONS
from homeassistant.components.homeassistant import KEY_HA_STOP
from homeassistant.components.persistent_notification import (
    DOMAIN as PERSISTENT_NOTIFICATION_DOMAIN,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, RESTART_EXIT_CODE
from homeassistant.core import Event, HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import (
    DATA_COMPONENTS,
    DATA_CUSTOM_COMPONENTS,
    DATA_INTEGRATIONS,
    DATA_MISSING_PLATFORMS,
    Integration,
    async_get_integrations,
)
from homeassistant.setup import _async_setup_component, async_setup_component
from homeassistant.util.async_ import create_eager_task

_LOGGER = logging.getLogger(__name__)

DOMAIN = "early_loader"


def _schema_validator(remove_extra=False):
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


CONFIG_SCHEMA = vol.Schema(_schema_validator())


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the component."""
    if PERSISTENT_NOTIFICATION_DOMAIN in hass.config.components:
        if await hass.async_add_executor_job(_setup_subcomponents, hass):
            _LOGGER.warning("Early Loader is initializing. Restarting Home Assistant")

            @callback
            def restart(_: Event | None = None) -> None:
                """Restart Home Assistant."""
                hass.data[KEY_HA_STOP] = asyncio.create_task(
                    hass.async_stop(RESTART_EXIT_CODE),
                )

            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, restart)

            return False

    if PERSISTENT_NOTIFICATION_DOMAIN not in CORE_INTEGRATIONS:
        _LOGGER.error(
            "PERSISTENT_NOTIFICATION no longer in CORE_INTEGRATIONS: early loading not executed"
        )

    result = await _async_setup_persistent_notification(hass, config)
    if not result:
        _LOGGER.error("Persistent Notification setup fail")
        return result

    await _async_setup_clients(hass, config)

    return True


async def _async_setup_clients(hass: HomeAssistant, config: ConfigType) -> None:
    domains = await _async_get_clients(hass, config)
    if not domains:
        return

    tasks = {
        create_eager_task(
            async_setup_component(hass, domain, config),
            name=f"setup component {domain}",
            loop=hass.loop,
        )
        for domain in domains
        if domain not in hass.config.components
    }
    # async_freeze has to match async_timeout in homeassistant.setup._async_setup_component
    # this prevents the timeout from cancelling us
    # we could also use homeassistant.setup.async_pause_setup to not count below integrations
    # setup time towards our own setup time reported in diagnostics, etc.
    async with hass.timeout.async_freeze(DOMAIN):
        await asyncio.gather(*tasks, return_exceptions=True)


async def _async_get_clients(
    hass: HomeAssistant, config: ConfigType
) -> Collection[str]:
    domains = {cv.domain_key(key) for key in config}

    integrations_or_excs = await async_get_integrations(hass, domains)

    clients: list[str] = []
    for domain, integration in integrations_or_excs.items():
        if not isinstance(integration, Integration):
            continue

        if dependencies := integration.manifest.get("dependencies"):
            try:
                dependencies.remove(DOMAIN)
            except ValueError:
                continue

            clients.append(domain)

    # legacy, to be removed in 2025.7
    DOMAINS_SCHEMA = vol.Schema(_schema_validator(True))
    clients_with_explicit_hook = DOMAINS_SCHEMA(config)
    return set(clients) | set(clients_with_explicit_hook)


def _setup_subcomponents(hass: HomeAssistant) -> bool:
    _LOGGER.debug("Setting up subcomponents")

    custom_components = Path(hass.config.config_dir) / "custom_components"
    self_component = custom_components / DOMAIN

    changes = False
    for manifest in self_component.rglob("subcomponents/*/manifest.json"):
        src_name = manifest.parent.name
        _LOGGER.debug("Setting up subcomponent %s", src_name)

        src_link = f"{DOMAIN}/subcomponents/{src_name}"
        src = custom_components / src_link
        dst = custom_components / src_name

        if dst.exists():
            if dst.resolve() == src.resolve():
                continue
            shutil.rmtree(dst)

        dst.symlink_to(src_link)
        changes = True

    return changes


async def _async_setup_persistent_notification(
    hass: HomeAssistant, config: ConfigType
) -> bool:
    """Set up built-in persistent notification.

    Has to be compatible with the workings of
    homeassistant.setup.{async_setup_component,_async_setup_component}.
    """
    integration, component = await _clear_caches(hass, PERSISTENT_NOTIFICATION_DOMAIN)

    # same comments apply below as they do in _async_setup_others
    async with hass.timeout.async_freeze(DOMAIN):
        result = await _async_setup_component(
            hass, PERSISTENT_NOTIFICATION_DOMAIN, config
        )

    async def async_get_component():
        return component

    integration.async_get_component = async_get_component  # type: ignore[method-assign]

    return result


async def _clear_caches(hass: HomeAssistant, domain: str) -> tuple[Integration, Any]:
    """Clear caches.

    Look at:
    - homeassistant.loader.async_get_integrations
    - homeassistant.loader.async_get_custom_components
    - homeassistant.loader.Integration.get_component
    - homeassistant.loader.Integration.{,async_}get_platform

    Returns custom domain integration and component.
    """
    integration_cache = hass.data[DATA_INTEGRATIONS]
    integration = cast(Integration, integration_cache.pop(domain))

    component = await integration.async_get_component()

    custom_integration_cache = cast(
        dict[str, Integration], hass.data[DATA_CUSTOM_COMPONENTS]
    )
    custom_integration_cache.pop(domain)

    component_cache = hass.data[DATA_COMPONENTS]
    component = component_cache.pop(domain)

    missing_platforms_cache = hass.data[DATA_MISSING_PLATFORMS]
    missing_platforms_cache.clear()

    return integration, component
