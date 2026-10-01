# Installation

Requires **Home Assistant 2026.9** or newer.

## With HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=archofthings&repository=home-assistant-frank-energie&category=integration)

Or by hand:

1. Open **HACS**.
2. Open the menu (⋮) → **Custom repositories**.
3. Add `https://github.com/archofthings/home-assistant-frank-energie` with type **Integration**.
4. Search for **Frank Energie**, open it and choose **Download**.
5. Restart Home Assistant.

## Manual install

1. Download `frank_energie.zip` from the [latest release](https://github.com/archofthings/home-assistant-frank-energie/releases).
2. Extract it into `config/custom_components/frank_energie/` (create the folder if needed). The folder must contain `manifest.json` directly, not a nested folder.
3. Restart Home Assistant.

## Add the integration

[![Open your Home Assistant instance and start setting up Frank Energie.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=frank_energie)

Or go to **Settings → Devices & services → Add integration → Frank Energie**. The steps are described in [Configuration](Configuration).

## Updating

HACS shows an update when a new release is published. Download it and restart Home Assistant. Your settings, entity IDs and history are kept. The [release notes](https://github.com/archofthings/home-assistant-frank-energie/releases) say what changed.

## Removing

1. **Settings → Devices & services → Frank Energie** → menu (⋮) → **Delete**.
2. In HACS, open Frank Energie → menu (⋮) → **Remove**.
3. Restart Home Assistant.

Imported [Energy dashboard statistics](Energy-dashboard-statistics) are not deleted with the integration. Remove them under **Developer tools → Statistics** if you no longer want them.

## Coming from the original integration?

See [Upgrading](Upgrading).
