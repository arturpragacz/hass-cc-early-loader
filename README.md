# Early Loader

This custom integration provides a hook that allows other integrations to load early in the Home Assistant initialisation sequence.

## Installation

This integration can be installed using [HACS](https://hacs.xyz/).

- Add a new custom repository to HACS (in the three dot menu).
- Insert the link to this repository.
- Select `integration`.
- Click the add button.
- The integration should now display in HACS.
- Install it like every other HACS integration.
- Restart Home Assistant.

## Configuration

In order to use this integration add `early_loader_hook: true` below the integration entry that you want to load early in `configuration.yaml`.
