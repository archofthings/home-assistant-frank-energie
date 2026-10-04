# Frank Energie for Home Assistant

[![Latest release](https://img.shields.io/github/v/release/archofthings/home-assistant-frank-energie?include_prereleases&sort=semver&label=release)](https://github.com/archofthings/home-assistant-frank-energie/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![CI](https://img.shields.io/github/actions/workflow/status/archofthings/home-assistant-frank-energie/ci.yaml?branch=main&label=CI)](https://github.com/archofthings/home-assistant-frank-energie/actions/workflows/ci.yaml)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.9%2B-41BDF5.svg?logo=homeassistant)](https://www.home-assistant.io/)
[![Downloads](https://img.shields.io/github/downloads/archofthings/home-assistant-frank-energie/total?label=downloads)](https://github.com/archofthings/home-assistant-frank-energie/releases)

A Home Assistant custom integration for [Frank Energie](https://www.frankenergie.nl/): electricity and gas prices per quarter-hour or per hour, a price analysis for automations and charts, and optionally your own usage, costs and invoices.

> [!NOTE]
> This project continues [bajansen/home-assistant-frank_energie](https://github.com/bajansen/home-assistant-frank_energie), which is no longer maintained. See [Project history](#project-history).

![Today's prices coloured by level, with the Sell line and the solar forecast](https://raw.githubusercontent.com/archofthings/home-assistant-frank-energie/main/images/prices_today.png)

**📖 Full documentation: the [wiki](https://github.com/archofthings/home-assistant-frank-energie/wiki)**, with every setting, sensor and attribute explained, a [chart gallery](https://github.com/archofthings/home-assistant-frank-energie/wiki/Chart-gallery) and [automation examples](https://github.com/archofthings/home-assistant-frank-energie/wiki/Automation-examples). This README is the short version.

## Contents

- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Sensors](#sensors)
- [Energy dashboard statistics](#energy-dashboard-statistics)
- [Price analysis](#price-analysis)
- [Charts](#charts)
- [Price list and get_prices action](#price-list-and-get_prices-action)
- [Upgrading from the original integration](#upgrading-from-the-original-integration)
- [Troubleshooting](#troubleshooting)
- [Documentation](#documentation)
- [Development](#development)
- [Project history](#project-history)
- [Credits](#credits)

## Features

- **Prices per quarter-hour or per hour** for electricity and gas: all-in, market price, tax, VAT and markup. No account needed.
- **Statistics:** lowest, highest and average price today and tomorrow, the next price, the lowest and highest price still to come, and a signal when tomorrow's prices arrive.
- **Price analysis:** every price slot (quarter-hour or hour) labelled cheap, normal or expensive (optionally "cheap + solar"), plus the cheapest block of hours you choose. Chart-ready.
- **With your Frank Energie login:** your contract prices, monthly costs, invoices, yearly totals, and yesterday's and this month's usage, costs and feed-in.
- **Energy dashboard statistics:** Frank Energie's hourly usage and costs as long-term statistics.
- **Choose your sensors** in groups, so you only get what you use.
- **`frank_energie.get_prices` action** with all prices and components, for scripts and automations.
- **Reliable:** the last prices stay available when the API has a hiccup, tokens renew automatically, and tomorrow's prices are picked up within 15 minutes of publication.
- Delivery address choice, local or UTC times, Netherlands and Belgium, and a diagnostics download for bug reports.

## Installation

Requires **Home Assistant 2026.9** or newer.

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=archofthings&repository=home-assistant-frank-energie&category=integration)

Or add it by hand: in HACS, open the menu (⋮) → **Custom repositories**, add `https://github.com/archofthings/home-assistant-frank-energie` as type **Integration**, download **Frank Energie** and restart Home Assistant.

*Manual install:* extract `frank_energie.zip` from the [latest release](https://github.com/archofthings/home-assistant-frank-energie/releases) into `config/custom_components/frank_energie/` and restart.

## Configuration

[![Open your Home Assistant instance and start setting up Frank Energie.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=frank_energie)

1. **Settings → Devices & services → Add integration → Frank Energie.**
2. Log in with your Frank Energie account, or continue without it for public prices only.
3. If your account has more than one address in delivery, choose one. Change it later with **Reconfigure** in the integration menu (⋮).
4. Choose your settings: the time zone for price times, the price resolution (without an account) and the sensor groups. With *Price analysis* ticked, a page with its settings follows. Everything can be changed later under [Options](#options).

If your login expires and can't be renewed, Home Assistant asks you to re-authenticate. The old `configuration.yaml` setup is no longer supported.

### Options

Choose **Configure** on the integration.

**Page 1:** the time zone for price times, the [price resolution](#price-resolution-quarter-hour-or-hourly-prices) and the sensor groups:

| Group | Entities | Default |
|---|---|---|
| *Current prices* | Current all-in, market and including-tax prices (+ hidden VAT, markup and tax sensors), electricity and gas | Always on |
| **Daily statistics** | Lowest, highest and average electricity price today; lowest and highest gas price today | On |
| **Upcoming and tomorrow prices** | Next price; tomorrow's average, lowest and highest; lowest and highest upcoming; *Tomorrow's prices available* | Off |
| **Price analysis** | See [Price analysis](#price-analysis) | Off |
| **Costs and invoices** 🔑 | Monthly costs, invoices, total this year and last year, price resolution | On |
| **Daily usage and costs** 🔑 | Yesterday's electricity, gas and feed-in usage and costs | Off |
| **Monthly usage and costs** 🔑 | This month's usage and costs, with expected values | Off |
| **Energy dashboard statistics** 🔑 | Hourly usage and costs as long-term statistics, see [Energy dashboard statistics](#energy-dashboard-statistics) | Off |

🔑 = only when logged in. Installations set up before groups existed keep all their sensors. Unticking a group removes its entities; ticking it again brings them back with the same entity IDs and history.

**Page 2** (only with *Price analysis* ticked): the [price analysis](#price-analysis) settings.

#### Price resolution: quarter-hour or hourly prices

| Setup | Prices you get | How to change |
|---|---|---|
| Not logged in | Per quarter-hour (default) or per hour | **Configure** → **Price resolution** → *Per quarter-hour* or *Per hour* |
| Logged in | The resolution of your contract | Not in Home Assistant: the option is hidden. Change your contract's price resolution with Frank Energie. |

- The hourly prices come from Frank Energie itself; the integration does not calculate them. They equal the average of the four quarters of that hour.
- With *Per hour*, all price sensors, the `prices` attributes, the price analysis and the `get_prices` action use 24 hourly prices per day.
- When logged in, the **Price resolution** sensor (group *Costs and invoices*) shows your contract's resolution.

#### Time zone

The times in `prices`, `slots`, `from_time` and the action can be written in Home Assistant's time zone (default for new installations) or UTC (installations from before this option). The moments are the same, only the notation differs. Before switching, check automations and Node-RED flows that read these times as text, for example by adding a fixed offset or cutting the hour out of the string. Anything that parses the full time (`as_timestamp()`, `new Date()`, ApexCharts) keeps working.

## Sensors

Prices are fetched every hour, and every 15 minutes from 12:00 until tomorrow's prices are published (usually around 13:00). Sensor states switch at every quarter hour to the current slot. A sensor is **unavailable** when there's no data for it, for example the tomorrow sensors before publication.

**Prices** (electricity €/kWh, gas €/m³):
- *Current:* all-in, market price, including tax; VAT, sourcing markup and tax only are disabled by default.
- *Statistics:* lowest, highest and average price today; next price; tomorrow's average, lowest and highest; lowest and highest upcoming price. Lowest/highest/next have a `from_time` attribute.
- The current all-in, market and including-tax sensors have the [`prices` attribute](#price-list-and-get_prices-action).
- *Tomorrow's prices available* (binary sensor) turns on when tomorrow's electricity prices arrive, and off again after midnight.

**Costs and invoices** 🔑: actual and expected monthly costs; the previous, current and upcoming invoice; the total of this year and last year (with an `invoices` attribute per period); and the price resolution of your contract.

**Usage and costs** 🔑 (fetched every 3 hours):

| | Daily (yesterday) | Monthly (this month) |
|---|---|---|
| Sensors | Electricity usage and costs, gas usage and costs, feed-in and feed-in revenue | The same, plus fixed costs (expected) |
| Attributes | `date`, `hours` (per hour) | `expected_usage` or `expected_costs`, `average_price`, `last_meter_reading` |

- The daily sensors show **yesterday**, because Frank Energie receives smart meter data a day later. In long-term statistics each day's value therefore lands **one day late**; for the Energy dashboard keep using your own meter.
- Gas and feed-in sensors are only created when your account has gas or feed-in data. Feed-in and its revenue are positive numbers.

## Energy dashboard statistics

Tick **Energy dashboard statistics** 🔑 under **Configure** to import Frank Energie's hourly usage and costs as long-term statistics. This creates no entities; six statistics appear in the pickers of the Energy dashboard: electricity usage, electricity costs, feed-in, feed-in revenue, gas usage and gas costs. For example:

- *Grid consumption:* Frank electricity usage, with **Use an entity tracking the total costs** set to Frank electricity costs.
- *Return to grid:* Frank feed-in, with Frank feed-in revenue as the compensation.
- *Gas consumption:* Frank gas usage, with Frank gas costs.

Frank Energie publishes yesterday's usage, so the data arrives a day later. The first time 30 days are imported, which takes a few minutes; after that the last 2 days are imported again every 3 hours to pick up corrections. Unticking the group stops the import and keeps the statistics already imported.

## Price analysis

Two independent calculations for electricity, set on page 2 of **Configure**:

**1. Price levels (fixed prices):** every slot gets a level:

| Level | Meaning | Setting (default) |
|---|---|---|
| `cheap_solar` | Cheap, and the solar forecast is at or above the threshold | Solar forecast (none), solar threshold (1.5 kWh/h) |
| `cheap` | All-in price at or below the cheap price | Cheap price below (€0.25) |
| `normal` | Between the two | |
| `expensive` | All-in price above the expensive price | Expensive price above (€0.40) |

The solar forecast can come from any integration that provides one for the Energy dashboard, such as Forecast.Solar or Solcast.

**2. Cheapest period (relative):** the consecutive block of the chosen length (15 minutes to 6 hours, default 2 hours) with the lowest average price, whatever the price. It's calculated for today, for tomorrow and from now on. With **Only when cheap** ticked, *Cheapest electricity period now* only turns on when that period's average price is also at or below the cheap price.

| Entity | State |
|---|---|
| Electricity price level | Level of the current slot |
| Cheap electricity price now | On while the current slot is cheap or cheap + solar |
| Cheapest electricity period now | On during today's cheapest period (optionally only when it's also cheap) |
| Next cheapest electricity period | Start of the next cheapest period (attributes `end`, `average_price`, `minutes`) |
| Electricity price analysis today / tomorrow | Start of that day's cheapest period, with chart attributes (not recorded): `slots` (per slot: `from`, `till`, `price`, `level`, `solar_kwh`, `in_cheapest_period`, `is_current`), `cheapest_period`, `cheap_windows`, `expensive_windows`, `solar_windows`, `thresholds` |

Example automations:

```yaml
# Start the dishwasher at the beginning of today's cheapest period
triggers:
  - trigger: state
    entity_id: binary_sensor.frank_energie_prices_cheapest_electricity_period_now
    to: "on"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.dishwasher
```

```yaml
# Charge the home battery whenever the price is cheap
triggers:
  - trigger: state
    entity_id: binary_sensor.frank_energie_prices_cheap_electricity_price_now
    to: ["on", "off"]
actions:
  - action: "switch.turn_{{ trigger.to_state.state }}"
    target:
      entity_id: switch.battery_charging
```

More about the levels, the cheapest period and all attributes: [Price analysis](https://github.com/archofthings/home-assistant-frank-energie/wiki/Price-analysis) on the wiki. More examples: [Automation examples](https://github.com/archofthings/home-assistant-frank-energie/wiki/Automation-examples).

Entity IDs in this README are those of a new installation. Installations upgraded from the original integration keep their older IDs without the `frank_energie_prices_` prefix.

## Charts

[ApexCharts Card](https://github.com/RomRider/apexcharts-card) cards for the price analysis: columns coloured by level (yellowgreen = cheap + solar, green = cheap, yellow = normal, red = expensive) and the solar forecast on the right axis. The screenshot at the top shows the *today* card. The wiki's [chart gallery](https://github.com/archofthings/home-assistant-frank-energie/wiki/Chart-gallery) has many more: today and tomorrow in one chart, prices without the price analysis, gas, usage and costs per day and per month, and invoices per month.

![Tomorrow's prices coloured by level, with the solar forecast](https://raw.githubusercontent.com/archofthings/home-assistant-frank-energie/main/images/prices_tomorrow.png)

Tips:
- Use **one** column series with a `colorMap`; separate series per level make the bars very narrow.
- Don't return `null` values or use an `area` series; the card then stays on "Loading".
- `+ 30 * 60 * 1000` centres the columns for **hourly** prices; with 15-minute prices use `+ 7.5 * 60 * 1000` (also in the tooltip).
- If a card shows nothing at all, check the pasted `data_generator` code is complete; a truncated line stops the whole card.

<details>
<summary><b>Today card</b> (with an optional <i>Sell</i> line: price minus a fixed feed-in amount)</summary>

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Today's Energy Prices
graph_span: 24h
span:
  start: day
now:
  show: true
  color: black
  label: Now
yaxis:
  - id: price
    decimals: 2
    min: 0
    max: 0.8
    apex_config:
      tickAmount: 8
  - id: solar
    opposite: true
    decimals: 1
    min: 0
    max: 5
series:
  - entity: sensor.frank_energie_prices_electricity_price_analysis_today
    name: Price
    type: column
    yaxis_id: price
    float_precision: 3
    data_generator: >
      if (!entity.attributes.slots || entity.attributes.slots.length === 0) {
        return [{ x: Date.now(), y: 0 }];
      }

      const colorMap = { cheap_solar: 'yellowgreen', cheap: 'green', normal:
      '#FFC107', expensive: '#F44336' };

      return entity.attributes.slots.map((p) => {
        const centeredX = new Date(p.from).getTime() + 30 * 60 * 1000;
        return { x: centeredX, y: p.price, fillColor: colorMap[p.level] };
      });
  - entity: sensor.frank_energie_prices_electricity_price_analysis_today
    name: Sell
    type: line
    color: green
    yaxis_id: price
    float_precision: 3
    stroke_width: 3
    data_generator: >
      if (!entity.attributes.slots || entity.attributes.slots.length === 0) {
        return [{ x: Date.now(), y: 0 }];
      }

      return entity.attributes.slots.map((p) => {
        const centeredX = new Date(p.from).getTime() + 30 * 60 * 1000;
        return { x: centeredX, y: p.price - 0.11085 };
      });
  - entity: sensor.frank_energie_prices_electricity_price_analysis_today
    name: Solar forecast
    type: line
    yaxis_id: solar
    color: '#2196F3'
    stroke_width: 3
    data_generator: >
      if (!entity.attributes.slots || entity.attributes.slots.length === 0) {
        return [{ x: Date.now(), y: 0 }];
      }

      return entity.attributes.slots.map((p) => {
        const centeredX = new Date(p.from).getTime() + 30 * 60 * 1000;
        return { x: centeredX, y: p.solar_kwh };
      });
apex_config:
  chart:
    height: 220
  xaxis:
    labels:
      datetimeUTC: false
  plotOptions:
    bar:
      columnWidth: 80%
  tooltip:
    x:
      formatter: |
        EVAL:function(val) {
          const realStart = new Date(val - 30 * 60 * 1000);
          return realStart.toLocaleString('nl-NL', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
        }
grid_options:
  columns: 24
  rows: auto
```

</details>

<details>
<summary><b>Tomorrow card</b> (empty until tomorrow's prices are published)</summary>

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Tomorrow's Energy Prices
graph_span: 24h
span:
  start: day
  offset: +1d
yaxis:
  - id: price
    decimals: 2
    min: 0
    max: 0.8
    apex_config:
      tickAmount: 8
  - id: solar
    opposite: true
    decimals: 1
    min: 0
    max: 5
series:
  - entity: sensor.frank_energie_prices_electricity_price_analysis_tomorrow
    name: Price
    type: column
    yaxis_id: price
    float_precision: 3
    data_generator: >
      if (!entity.attributes.slots || entity.attributes.slots.length === 0) {
        return [{ x: Date.now(), y: 0 }];
      }

      const colorMap = { cheap_solar: 'yellowgreen', cheap: 'green', normal:
      '#FFC107', expensive: '#F44336' };

      return entity.attributes.slots.map((p) => {
        const centeredX = new Date(p.from).getTime() + 30 * 60 * 1000;
        return { x: centeredX, y: p.price, fillColor: colorMap[p.level] };
      });
  - entity: sensor.frank_energie_prices_electricity_price_analysis_tomorrow
    name: Solar forecast
    type: line
    yaxis_id: solar
    color: '#2196F3'
    stroke_width: 3
    data_generator: >
      if (!entity.attributes.slots || entity.attributes.slots.length === 0) {
        return [{ x: Date.now(), y: 0 }];
      }

      return entity.attributes.slots.map((p) => {
        const centeredX = new Date(p.from).getTime() + 30 * 60 * 1000;
        return { x: centeredX, y: p.solar_kwh };
      });
apex_config:
  chart:
    height: 220
  xaxis:
    labels:
      datetimeUTC: false
  plotOptions:
    bar:
      columnWidth: 80%
  tooltip:
    x:
      formatter: |
        EVAL:function(val) {
          const realStart = new Date(val - 30 * 60 * 1000);
          return realStart.toLocaleString('nl-NL', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
        }
grid_options:
  columns: 24
  rows: auto
```

</details>

### Costs this month

Two rows of [Mushroom](https://github.com/piitaya/lovelace-mushroom) tiles (version 5 or newer) for a logged-in account, like the overview in the Frank Energie app. The first row shows the expected costs up to the last meter reading, the real costs and the difference, with percentages compared to the expected costs; a negative difference means you are below the expected costs.

![Expected costs, real costs and the difference of this month as three tiles](https://raw.githubusercontent.com/archofthings/home-assistant-frank-energie/main/images/costs_this_month.png)

<details>
<summary><b>This month card</b></summary>

```yaml
type: grid
columns: 3
square: false
cards:
  - type: custom:mushroom-template-card
    primary: Expected
    secondary: '€ {{ "%.2f" | format(states("sensor.frank_energie_costs_expected_monthly_cost_until_now") | float(0)) | replace(".", ",") }}'
    icon: mdi:crystal-ball
    color: orange
    tap_action:
      action: none
  - type: custom:mushroom-template-card
    primary: Real costs
    secondary: |-
      {% set e = states("sensor.frank_energie_costs_expected_monthly_cost_until_now") | float(0) %}
      {% set a = states("sensor.frank_energie_costs_actual_monthly_cost") | float(0) %}
      € {{ "%.2f" | format(a) | replace(".", ",") }}{% if e > 0 %} ({{ (a / e * 100) | round(0) | int }}%){% endif %}
    multiline_secondary: true
    icon: mdi:cash
    color: red
    tap_action:
      action: none
  - type: custom:mushroom-template-card
    primary: Difference
    secondary: |-
      {% set e = states("sensor.frank_energie_costs_expected_monthly_cost_until_now") | float(0) %}
      {% set a = states("sensor.frank_energie_costs_actual_monthly_cost") | float(0) %}
      € {{ "%+.2f" | format(a - e) | replace(".", ",") }}{% if e > 0 %} ({{ "%+d" | format(((a - e) / e * 100) | round(0) | int) }}%){% endif %}
    multiline_secondary: true
    icon: mdi:swap-vertical
    color: blue
    tap_action:
      action: none
```

</details>

The second row shows the usage and costs of gas, electricity and feed-in this month, and the fixed costs so far (calculated: the real costs minus gas and electricity, plus the feed-in revenue).

![Usage and costs of gas, electricity and feed-in, and the fixed costs, as four tiles](https://raw.githubusercontent.com/archofthings/home-assistant-frank-energie/main/images/costs_breakdown.png)

<details>
<summary><b>Cost breakdown card</b></summary>

```yaml
type: grid
columns: 4
square: false
cards:
  - type: custom:mushroom-template-card
    primary: Gas
    secondary: |-
      {{ "%.1f" | format((states("sensor.frank_energie_costs_gas_usage_this_month") | float(0))) | replace(".", ",") }} m³
      € {{ "%.2f" | format((states("sensor.frank_energie_costs_gas_costs_this_month") | float(0))) | replace(".", ",") }}
    multiline_secondary: true
    icon: mdi:fire
    color: light-blue
    vertical: true
    tap_action:
      action: none
  - type: custom:mushroom-template-card
    primary: Electricity
    secondary: |-
      {{ "%.1f" | format((states("sensor.frank_energie_costs_electricity_usage_this_month") | float(0))) | replace(".", ",") }} kWh
      € {{ "%.2f" | format((states("sensor.frank_energie_costs_electricity_costs_this_month") | float(0))) | replace(".", ",") }}
    multiline_secondary: true
    icon: mdi:lightning-bolt
    color: amber
    vertical: true
    tap_action:
      action: none
  - type: custom:mushroom-template-card
    primary: Feed-in
    secondary: |-
      {{ "%.1f" | format(-(states("sensor.frank_energie_costs_feed_in_this_month") | float(0))) | replace(".", ",") }} kWh
      € {{ "%.2f" | format(-(states("sensor.frank_energie_costs_feed_in_revenue_this_month") | float(0))) | replace(".", ",") }}
    multiline_secondary: true
    icon: mdi:solar-panel
    color: deep-orange
    vertical: true
    tap_action:
      action: none
  - type: custom:mushroom-template-card
    primary: Fixed
    secondary: |-
      until now
      € {{ "%.2f" | format(states("sensor.frank_energie_costs_actual_monthly_cost") | float(0) - states("sensor.frank_energie_costs_gas_costs_this_month") | float(0) - states("sensor.frank_energie_costs_electricity_costs_this_month") | float(0) + states("sensor.frank_energie_costs_feed_in_revenue_this_month") | float(0)) | replace(".", ",") }}
    multiline_secondary: true
    icon: mdi:calendar-month
    color: grey
    vertical: true
    tap_action:
      action: none
```

</details>

The amounts use a decimal comma; remove `| replace(".", ",")` for a decimal point. The [chart gallery](https://github.com/archofthings/home-assistant-frank-energie/wiki/Chart-gallery) also has a month chart with month buttons and a chart of real and saved costs per month.

## Price list and get_prices action

The current all-in, market and including-tax sensors have a `prices` attribute: every known price slot (quarter-hour or hour) for today and tomorrow as `from`, `till` and `price` (3 decimals). It's up to 200 entries, so it's **not stored in history**, but it's always available on the live state. Example, the lowest price in the next six hours:

```jinja
{{ state_attr('sensor.frank_energie_prices_current_electricity_price_all_in', 'prices')
   | selectattr('from', 'gt', now())
   | selectattr('till', 'lt', now() + timedelta(hours=6))
   | min(attribute='price') }}
```

The **`frank_energie.get_prices`** action returns the same slots with all components (`price`, `market_price`, `market_price_including_tax`, `vat`, `sourcing_markup`, `energy_tax`) for `electricity` and `gas`. Optional `start` and `end` limit the period; it doesn't call the API. Pick your entry in **Developer tools → Actions** to find its `config_entry_id`.

```yaml
- action: frank_energie.get_prices
  data:
    config_entry_id: YOUR_ENTRY_ID
    start: "{{ now() }}"
    end: "{{ now() + timedelta(hours=6) }}"
  response_variable: frank
- action: notify.notify
  data:
    message: >
      {% set c = frank.electricity | min(attribute='price') %}
      Cheapest at {{ c.start }}: € {{ c.price }}/kWh
```

## Upgrading from the original integration

1. In HACS, **Remove** Frank Energie. This only removes the files; your integration, entities and history stay.
2. Remove the old custom repository (`bajansen/home-assistant-frank_energie` or `archofthings/home-assistant-frank_energie`), then add this one and download it as described under [Installation](#installation).
3. Restart Home Assistant.

Entity IDs and history are kept. What changes: Home Assistant 2026.9+ is required; prices are per quarter-hour by default (96 per day, 92/100 on daylight-saving days), so today's lowest/highest can be more extreme than the old hourly values (for hourly prices see [Price resolution](#price-resolution-quarter-hour-or-hourly-prices)); the `prices` attribute is no longer stored in history.

## Troubleshooting

- **Sensors unavailable:** tomorrow's sensors wait for publication (around 13:00); gas sensors stay unavailable without a gas contract.
- **Cost, invoice or monthly usage sensors unavailable while prices work:** Frank Energie's service for that data is failing (the log has a "Could not fetch" or "Could not update" warning). Prices keep updating and the sensors come back by themselves. On the 1st of the month the monthly usage sensors can be unavailable until Frank Energie has data for the new month.
- **Known issue, cost numbers show different days:** the expected and actual monthly costs, the daily and monthly usage and costs, and the statistics come from separate Frank Energie services. The integration refreshes all of them as soon as one has a new day, but Frank Energie sometimes publishes them hours apart. Until then they can differ by a day; this is on Frank Energie's side and resolves by itself.
- **Chart empty or stuck on "Loading":** see the chart [tips](#charts).
- **Diagnostics:** integration menu (⋮) → **Download diagnostics**. Tokens, username, site reference and address are removed.
- **Debug logging:**

  ```yaml
  logger:
    logs:
      custom_components.frank_energie: debug
      python_frank_energie: debug
  ```

  Library debug logs can contain your address and price data; remove personal details before sharing. The integration never logs tokens or passwords.

More problems and solutions, and the meaning of the log messages: [Troubleshooting](https://github.com/archofthings/home-assistant-frank-energie/wiki/Troubleshooting) on the wiki. Report problems via [GitHub issues](https://github.com/archofthings/home-assistant-frank-energie/issues).

## Documentation

The [wiki](https://github.com/archofthings/home-assistant-frank-energie/wiki) has the full documentation:

| Page | Contents |
|---|---|
| [Installation](https://github.com/archofthings/home-assistant-frank-energie/wiki/Installation) | HACS, manual install, updating, removing |
| [Configuration](https://github.com/archofthings/home-assistant-frank-energie/wiki/Configuration) | Setup, re-authenticate, reconfigure and every option explained |
| [Sensors](https://github.com/archofthings/home-assistant-frank-energie/wiki/Sensors) | Every entity with its state and attributes |
| [Price analysis](https://github.com/archofthings/home-assistant-frank-energie/wiki/Price-analysis) | Price levels, cheapest period, solar forecast |
| [Energy dashboard statistics](https://github.com/archofthings/home-assistant-frank-energie/wiki/Energy-dashboard-statistics) | Frank Energie's usage and costs in the Energy dashboard |
| [Price list and get_prices action](https://github.com/archofthings/home-assistant-frank-energie/wiki/Price-list-and-get_prices-action) | The `prices` attribute and the action, with templates |
| [Chart gallery](https://github.com/archofthings/home-assistant-frank-energie/wiki/Chart-gallery) | Ready-to-use dashboard cards |
| [Automation examples](https://github.com/archofthings/home-assistant-frank-energie/wiki/Automation-examples) | Ready-to-use automations |
| [How it works](https://github.com/archofthings/home-assistant-frank-energie/wiki/How-it-works) | Update schedule, error handling, privacy |
| [Troubleshooting](https://github.com/archofthings/home-assistant-frank-energie/wiki/Troubleshooting) | Problems, log messages, diagnostics |
| [Upgrading](https://github.com/archofthings/home-assistant-frank-energie/wiki/Upgrading) | Moving from the original integration |

## Development

Python 3.14. Run the checks like CI does:

```bash
python3.14 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/flake8 . --count --max-complexity=10 --max-line-length=120 --statistics
.venv/bin/pytest
```

`CLAUDE.md` has a module map of `custom_components/frank_energie/`. The tests mock the Frank Energie API completely. Publishing a GitHub release builds `frank_energie.zip` for HACS. The wiki pages are kept in the `wiki/` folder.

## Project history

Created as [bajansen/home-assistant-frank_energie](https://github.com/bajansen/home-assistant-frank_energie) by [@bajansen](https://github.com/bajansen) and contributors, and developed there until early 2025. When Frank Energie changed its API in 2026, development continued here, keeping the full commit history, the `frank_energie` domain and the entity unique IDs.

## Credits

- **[@HiDiHo01](https://github.com/HiDiHo01)** maintains [python-frank-energie](https://github.com/HiDiHo01/python-frank-energie), the API client this integration uses for all communication with Frank Energie ([PyPI](https://pypi.org/project/python-frank-energie/), Apache-2.0).
- **[@bajansen](https://github.com/bajansen)** and the contributors of the original integration.

Not affiliated with or endorsed by Frank Energie. The upstream project has no license file, so none has been added here.
