# Frank Energie for Home Assistant

[![Latest release](https://img.shields.io/github/v/release/archofthings/home-assistant-frank-energie?include_prereleases&sort=semver&label=release)](https://github.com/archofthings/home-assistant-frank-energie/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![CI](https://img.shields.io/github/actions/workflow/status/archofthings/home-assistant-frank-energie/ci.yaml?branch=main&label=CI)](https://github.com/archofthings/home-assistant-frank-energie/actions/workflows/ci.yaml)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.9%2B-41BDF5.svg?logo=homeassistant)](https://www.home-assistant.io/)
[![Downloads](https://img.shields.io/github/downloads/archofthings/home-assistant-frank-energie/total?label=downloads)](https://github.com/archofthings/home-assistant-frank-energie/releases)

A Home Assistant custom integration for [Frank Energie](https://www.frankenergie.nl/): electricity and gas prices per 15 minutes, a price analysis for automations and charts, and optionally your own usage, costs and invoices.

> [!NOTE]
> This project continues [bajansen/home-assistant-frank_energie](https://github.com/bajansen/home-assistant-frank_energie), which is no longer maintained. See [Project history](#project-history).

![Today's prices coloured by level, with the Sell line and the solar forecast](https://raw.githubusercontent.com/archofthings/home-assistant-frank-energie/main/images/prices_today.png)

## Contents

- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Sensors](#sensors)
- [Price analysis](#price-analysis)
- [Charts](#charts)
- [Price list and get_prices action](#price-list-and-get_prices-action)
- [Upgrading from the original integration](#upgrading-from-the-original-integration)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Project history](#project-history)

## Features

- **Prices every 15 minutes** for electricity and gas: all-in, market price, tax, VAT and markup. No account needed.
- **Statistics:** lowest, highest and average price today and tomorrow, the next price, and the lowest and highest price still to come.
- **Price analysis:** every quarter hour labelled cheap, normal or expensive (optionally "cheap + solar"), plus the cheapest block of hours you choose. Chart-ready.
- **With your Frank Energie login:** your contract prices, monthly costs, invoices, and yesterday's and this month's usage, costs and feed-in.
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

If your login expires and can't be renewed, Home Assistant asks you to re-authenticate. The old `configuration.yaml` setup is no longer supported.

### Options

Choose **Configure** on the integration.

**Page 1:** the time zone for price times, and the sensor groups:

| Group | Entities | Default |
|---|---|---|
| *Current prices* | Current all-in, market and including-tax prices (+ hidden VAT, markup and tax sensors), electricity and gas | Always on |
| **Daily statistics** | Lowest, highest and average price today | On |
| **Upcoming and tomorrow prices** | Next price; tomorrow's average, lowest and highest; lowest and highest upcoming | Off |
| **Price analysis** | See [Price analysis](#price-analysis) | Off |
| **Costs and invoices** 🔑 | Monthly costs and invoices | On |
| **Daily usage and costs** 🔑 | Yesterday's electricity, gas and feed-in usage and costs | Off |
| **Monthly usage and costs** 🔑 | This month's usage and costs, with expected values | Off |

🔑 = only when logged in. Installations set up before groups existed keep all their sensors. Unticking a group removes its entities; ticking it again brings them back with the same entity IDs and history.

**Page 2** (only with *Price analysis* ticked): the [price analysis](#price-analysis) settings.

**Time zone:** the times in `prices`, `slots`, `from_time` and the action can be written in Home Assistant's time zone (default for new installations) or UTC (installations from before this option). The moments are the same, only the notation differs. Before switching, check automations and Node-RED flows that read these times as text, for example by adding a fixed offset or cutting the hour out of the string. Anything that parses the full time (`as_timestamp()`, `new Date()`, ApexCharts) keeps working.

## Sensors

Prices are fetched every hour, and every 15 minutes from 12:00 until tomorrow's prices are published (usually around 13:00). Sensor states switch at every quarter hour to the current slot. A sensor is **unavailable** when there's no data for it, for example the tomorrow sensors before publication.

**Prices** (electricity €/kWh, gas €/m³):
- *Current:* all-in, market price, including tax; VAT, sourcing markup and tax only are disabled by default.
- *Statistics:* lowest, highest and average price today; next price; tomorrow's average, lowest and highest; lowest and highest upcoming price. Lowest/highest/next have a `from_time` attribute.
- The current all-in, market and including-tax sensors have the [`prices` attribute](#price-list-and-get_prices-action).

**Costs and invoices** 🔑: actual and expected monthly costs, and the previous, current and upcoming invoice.

**Usage and costs** 🔑 (fetched every 3 hours):

| | Daily (yesterday) | Monthly (this month) |
|---|---|---|
| Sensors | Electricity usage and costs, gas usage and costs, feed-in and feed-in revenue | The same, plus fixed costs (expected) |
| Attributes | `date`, `hours` (per hour) | `expected_usage` or `expected_costs`, `average_price`, `last_meter_reading` |

- The daily sensors show **yesterday**, because Frank Energie receives smart meter data a day later. In long-term statistics each day's value therefore lands **one day late**; for the Energy dashboard keep using your own meter.
- Gas and feed-in sensors are only created when your account has gas or feed-in data. Feed-in and its revenue are positive numbers.

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

**2. Cheapest period (relative):** the consecutive block of the chosen length (15 minutes to 6 hours, default 2 hours) with the lowest average price, whatever the price. It's calculated for today, for tomorrow and from now on.

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

Entity IDs in this README are those of a new installation. Installations upgraded from the original integration keep their older IDs without the `frank_energie_prices_` prefix.

## Charts

[ApexCharts Card](https://github.com/RomRider/apexcharts-card) cards for the price analysis: columns coloured by level (yellowgreen = cheap + solar, green = cheap, yellow = normal, red = expensive) and the solar forecast on the right axis. The screenshot at the top shows the *today* card.

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

## Price list and get_prices action

The current all-in, market and including-tax sensors have a `prices` attribute: every known 15-minute slot for today and tomorrow as `from`, `till` and `price` (3 decimals). It's up to 200 entries, so it's **not stored in history**, but it's always available on the live state. Example, the lowest price in the next six hours:

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

Entity IDs and history are kept. What changes: Home Assistant 2026.9+ is required; prices are per 15 minutes (96 per day, 92/100 on daylight-saving days), so today's lowest/highest can be more extreme than the old hourly values; the `prices` attribute is no longer stored in history.

## Troubleshooting

- **Sensors unavailable:** tomorrow's sensors wait for publication (around 13:00); gas sensors stay unavailable without a gas contract.
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

Report problems via [GitHub issues](https://github.com/archofthings/home-assistant-frank-energie/issues).

## Development

Python 3.14. Run the checks like CI does:

```bash
python3.14 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/flake8 . --count --max-complexity=10 --max-line-length=120 --statistics
.venv/bin/pytest
```

`CLAUDE.md` has a module map of `custom_components/frank_energie/`. The tests mock the Frank Energie API completely. Publishing a GitHub release builds `frank_energie.zip` for HACS.

## Project history

Created as [bajansen/home-assistant-frank_energie](https://github.com/bajansen/home-assistant-frank_energie) by [@bajansen](https://github.com/bajansen) and contributors, and developed there until early 2025. When Frank Energie changed its API in 2026, development continued here, keeping the full commit history, the `frank_energie` domain and the entity unique IDs. API client: [python-frank-energie](https://pypi.org/project/python-frank-energie/).

Not affiliated with or endorsed by Frank Energie. The upstream project has no license file, so none has been added here.
