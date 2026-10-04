# Upgrading

## From the original integration

This project continues [bajansen/home-assistant-frank_energie](https://github.com/bajansen/home-assistant-frank_energie). You can switch without losing anything: the integration domain (`frank_energie`) and the entity unique IDs are the same.

1. Make sure you run **Home Assistant 2026.9** or newer.
2. In HACS, open Frank Energie → menu (⋮) → **Remove**. This only removes the files; your integration, entities and history stay.
3. In HACS → menu (⋮) → **Custom repositories**, remove the old repository (`bajansen/home-assistant-frank_energie` or `archofthings/home-assistant-frank_energie`).
4. Add `https://github.com/archofthings/home-assistant-frank-energie` as type **Integration** and download **Frank Energie**, see [Installation](Installation).
5. Restart Home Assistant.

Do **not** delete the integration under **Settings → Devices & services**; that would remove your entities.

### What stays the same

- Entity IDs, names you gave, and history.
- Your login and chosen address.
- All sensors you had.

### What changes

| Change | What to do |
|---|---|
| Home Assistant 2026.9 or newer is required | Update Home Assistant first. |
| Prices are per quarter-hour by default (96 per day) | Today's lowest and highest price can be more extreme than the old hourly values. For hourly prices see [Price resolution](Configuration#price-resolution). |
| The `prices` attribute is no longer stored in history | Nothing; it is always on the live state. Automations that read it keep working. |
| Times in attributes stay in **UTC** for existing installations | Nothing. Switch to local time when you like, see [Time zone for price times](Configuration#time-zone-for-price-times). |
| Setup through `configuration.yaml` is gone | Use the UI. |
| New sensors come in groups | Tick the groups you want under **Configure**, see [Sensor groups](Configuration#sensor-groups). |

### After upgrading

- Open **Configure** once to see the new options and groups.
- If your automations or Node-RED flows assumed 24 prices per day, check them: there can be 96.
- Entity IDs on this wiki are those of a new installation; yours don't have the `frank_energie_prices_` prefix.

## Between versions of this integration

Update through HACS and restart. Settings, entity IDs and history are kept. New sensor groups are always **off** until you tick them, so an update never adds entities by itself.

The [release notes](https://github.com/archofthings/home-assistant-frank-energie/releases) list the changes of every version.

| Version | Main additions |
|---|---|
| 1.8 | Hourly prices for entries without a login; prices keep working when costs or invoices fail; settings are asked during setup (1.8.2); cost data refreshes together when one part has a new day, *Monthly cost difference until now* and *Fixed costs this month until now* sensors (1.8.3) |
| 1.7 | Energy dashboard statistics; *Only when cheap*; correction invoices added up per period |
| 1.6 | *Tomorrow's prices available*; total this year and last year; *Price resolution* sensor; Dutch and English entity names |
| 1.5 and earlier | `get_prices` action, extra price sensors, diagnostics, address choice, time zone option, price analysis, sensor groups, usage and costs |
