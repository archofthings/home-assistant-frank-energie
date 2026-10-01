# Configuration

Everything is set up in the Home Assistant UI. The old `configuration.yaml` setup is not supported.

- [First setup](#first-setup)
- [Re-authenticate](#re-authenticate)
- [Change the delivery address (Reconfigure)](#change-the-delivery-address-reconfigure)
- [Options page 1: general](#options-page-1-general)
  - [Time zone for price times](#time-zone-for-price-times)
  - [Price resolution](#price-resolution)
  - [Sensor groups](#sensor-groups)
- [Options page 2: price analysis settings](#options-page-2-price-analysis-settings)
- [All settings at a glance](#all-settings-at-a-glance)

## First setup

**Settings → Devices & services → Add integration → Frank Energie.**

### Step 1: sign in or not

| Field | Meaning |
|---|---|
| **Use Frank Energie account credentials** | Ticked: continue to the login step. Not ticked: the integration is added right away with Frank Energie's public prices. |

Without an account you get all price sensors, the price analysis and the `get_prices` action. With an account you also get your contract prices, costs, invoices, usage and the Energy dashboard statistics. See the table on the [Home](Home) page.

You can add **one** entry without an account, and one entry per Frank Energie account.

### Step 2: log in

| Field | Meaning |
|---|---|
| **Username / e-mail** | The e-mail address of your Frank Energie account. |
| **Password** | Your Frank Energie password. It is only used to log in once; Home Assistant stores the access and refresh tokens, not the password. |

| Message | Cause |
|---|---|
| *Credentials rejected, please check your username and password.* | Frank Energie refused the login. |
| *Failed to connect* | Frank Energie could not be reached. Try again later. |
| *Account is already configured* | This account already has an entry. |
| *No active delivery address was found for this account.* | The account has no address with status "in delivery" (for example before the contract starts or after it ended). |

### Step 3: choose your address

Only shown when your account has **more than one** address in delivery. With one address it is chosen for you. The entry gets the street and house number as its name.

### After setup

Two devices appear:

| Device | Contains |
|---|---|
| **Frank Energie - Prices** | Price sensors, price analysis, *Tomorrow's prices available* |
| **Frank Energie - Costs** | Costs, invoices, usage and the *Price resolution* sensor (only when logged in) |

A new installation starts with the sensor groups **Daily statistics** and **Costs and invoices**. Turn on more under [Sensor groups](#sensor-groups).

## Re-authenticate

Tokens are renewed automatically. If renewal is refused (for example after a password change), Home Assistant shows a **Re-authenticate** notice on the integration. Log in again with the **same** account.

Logging in with a different account is refused with *"The account you logged in with differs from the one configured for this entry."* Add the other account as a new Frank Energie integration instead.

## Change the delivery address (Reconfigure)

Integration menu (⋮) → **Reconfigure**. Choose another address of the same account; the entry is renamed and reloaded. Only for entries with a login.

Entities keep their entity IDs. From then on they show the data of the new address.

## Options page 1: general

Choose **Configure** on the integration. Saving reloads the integration by itself; no restart is needed.

### Time zone for price times

| Choice | Meaning |
|---|---|
| **Home Assistant's time zone** | Times are written in your local time, for example `2026-10-01T13:00:00+02:00`. Default for new installations. |
| **UTC** | Times are written in UTC, for example `2026-10-01T11:00:00+00:00`. Default for installations from before this option existed. |

This applies to the times in the `prices`, `slots` and `hours` attributes, the `from_time` attribute, the window attributes of the price analysis, and the `start`/`end` of the `get_prices` action.

The **moments are the same**, only the notation differs. Sensor states and Home Assistant's own timestamps are not affected.

> [!WARNING]
> Before switching, check automations and Node-RED flows that read these times **as text**, for example by adding a fixed offset or cutting the hour out of the string. Anything that parses the full time (`as_timestamp()`, `as_datetime()`, `new Date()`, ApexCharts) keeps working.

### Price resolution

Only shown when you are **not logged in**.

| Choice | Meaning |
|---|---|
| **Per quarter-hour** (default) | 96 electricity prices per day (92 or 100 on daylight-saving days). |
| **Per hour** | 24 electricity prices per day (23 or 25 on daylight-saving days). |

- The hourly prices come from Frank Energie itself; the integration does not calculate them. They equal the average of the four quarters of that hour.
- With *Per hour*, all price sensors, the `prices` attributes, the price analysis and the `get_prices` action use hourly prices.
- **Logged in?** The option is hidden: your prices follow the price resolution of your contract. Change that with Frank Energie, not in Home Assistant. The **Price resolution** sensor shows your contract's resolution, see [Sensors](Sensors#price-resolution).

### Sensor groups

Tick the groups you want. The current price sensors are always there.

| Group | Entities | New installation | Needs login |
|---|---|---|---|
| *Current prices* | Current all-in, market and including-tax price, plus VAT, markup and tax (disabled by default), for electricity and gas | Always on | |
| **Daily statistics** | Lowest, highest and average electricity price today; lowest and highest gas price today | On | |
| **Upcoming and tomorrow prices** | Next price; tomorrow's average, lowest and highest; lowest and highest upcoming; average gas price tomorrow; *Tomorrow's prices available* | Off | |
| **Price analysis** | Price level, cheap price now, cheapest period now, next cheapest period, analysis today and tomorrow | Off | |
| **Costs and invoices** | Monthly costs, invoices, total this year and last year, price resolution | On | 🔑 |
| **Daily usage and costs** | Yesterday's electricity, gas and feed-in usage and costs | Off | 🔑 |
| **Monthly usage and costs** | This month's usage and costs, with expected values and fixed costs | Off | 🔑 |
| **Energy dashboard statistics** | No entities: hourly usage and costs as long-term statistics | Off | 🔑 |

All entities per group are listed on the [Sensors](Sensors) page.

Good to know:

- **Unticking a group removes its entities.** Ticking it again brings them back with the same entity IDs and their history.
- Groups marked 🔑 are only offered when the entry is logged in.
- A group that is off costs nothing: no entities, no calculations and no extra calls to Frank Energie.
- Installations set up before groups existed keep the sensors they had (daily statistics, upcoming, price analysis, costs) until you change the selection.
- Unticking **Energy dashboard statistics** stops the import and keeps the statistics already imported.

## Options page 2: price analysis settings

Only shown when **Price analysis** is ticked on page 1. The two calculations are independent; see [Price analysis](Price-analysis) for how they work.

### Price levels (fixed prices)

| Setting | Default | Meaning |
|---|---|---|
| **Cheap price below (€/kWh)** | 0.25 | All-in electricity prices **at or below** this are *cheap*. Steps of €0.001. |
| **Expensive price above (€/kWh)** | 0.40 | All-in electricity prices **above** this are *expensive*. Steps of €0.001. Must be higher than the cheap price. |
| **Solar forecast** | none | Optional. An integration that forecasts your solar production. Cheap slots with enough forecast production become *cheap + solar*. Leave it empty to not use solar. |
| **Solar threshold** | 1.5 kWh | The forecast production, in kWh per hour, from which a cheap slot is marked *cheap + solar*. Steps of 0.1. |

The **Solar forecast** list shows every integration that provides a solar forecast for the Energy dashboard, such as Forecast.Solar or Solcast, as *name (integration)*. If the list is empty, no such integration is installed.

If you save a cheap price that is not lower than the expensive price, the form shows *"The cheap price threshold must be lower than the expensive price threshold."*

### Cheapest period (relative)

| Setting | Default | Meaning |
|---|---|---|
| **Cheapest period length** | 120 min | The length of the block to look for: 15 to 360 minutes, in steps of 15. With hourly prices the length is rounded up to whole hours. |
| **Only when cheap** | Off | On: *Cheapest electricity period now* only turns on when the period's average price is also at or below the cheap price. Off: it turns on during the cheapest period of every day, whatever the price. |

Your price analysis settings are remembered when you untick the group, and come back when you tick it again.

## All settings at a glance

| Where | Setting | Values | Default |
|---|---|---|---|
| Setup | Use Frank Energie account credentials | yes / no | no |
| Setup | Username, password | | |
| Setup, Reconfigure | Address | Addresses in delivery | The only one |
| Options 1 | Time zone for price times | Home Assistant's time zone / UTC | Home Assistant's time zone |
| Options 1 | Price resolution (not logged in) | Per quarter-hour / Per hour | Per quarter-hour |
| Options 1 | Sensor groups | 7 groups | Daily statistics, Costs and invoices |
| Options 2 | Cheap price below | €/kWh | 0.25 |
| Options 2 | Expensive price above | €/kWh | 0.40 |
| Options 2 | Solar forecast | A solar forecast integration | none |
| Options 2 | Solar threshold | kWh per hour | 1.5 |
| Options 2 | Cheapest period length | 15 to 360 min | 120 |
| Options 2 | Only when cheap | on / off | off |
