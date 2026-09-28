# Frank Energie for Home Assistant

[![Latest release](https://img.shields.io/github/v/release/archofthings/home-assistant-frank-energie?include_prereleases&sort=semver&label=release)](https://github.com/archofthings/home-assistant-frank-energie/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![CI](https://img.shields.io/github/actions/workflow/status/archofthings/home-assistant-frank-energie/ci.yaml?branch=main&label=CI)](https://github.com/archofthings/home-assistant-frank-energie/actions/workflows/ci.yaml)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.9%2B-41BDF5.svg?logo=homeassistant)](https://www.home-assistant.io/)
[![Installations](https://img.shields.io/badge/dynamic/json?label=installations&query=%24.frank_energie.total&url=https%3A%2F%2Fanalytics.home-assistant.io%2Fcustom_integrations.json)](https://analytics.home-assistant.io/)

A Home Assistant custom integration that brings [Frank Energie](https://www.frankenergie.nl/) electricity and gas prices into Home Assistant, with optional account data such as your monthly costs and invoices.

Use the price sensors to run appliances, charge a car or battery, or heat water when energy is cheapest.

> [!NOTE]
> This project continues [bajansen/home-assistant-frank_energie](https://github.com/bajansen/home-assistant-frank_energie), which is no longer actively maintained. See [Project history](#project-history).

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Sensors](#sensors)
- [Using the price list](#using-the-price-list)
- [Charts](#charts)
- [Upgrading from the original integration](#upgrading-from-the-original-integration)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Project history](#project-history)
- [Credits and license](#credits-and-license)

## Features

- **Current prices every 15 minutes**: all-in price, market price, price including tax, VAT, sourcing markup and energy tax, for electricity and gas.
- **Daily statistics**: lowest, highest and average price for today.
- **Full price list** as an attribute, covering today and (once published, usually around 13:00) tomorrow.
- **No account needed** for public prices.
- **Optional login** for your personal contract prices, plus your monthly cost and invoice sensors.
- **Your delivery address is detected automatically** when you log in.
- **Keeps working through API hiccups**: if an update fails, the last prices stay available as long as they still cover the future. Tokens are renewed automatically, and you're only asked to log in again when that fails.
- **Netherlands and Belgium**: public fallback prices follow your account's country.

## Requirements

- Home Assistant **2026.9** or newer
- [HACS](https://hacs.xyz/) (recommended) for installation
- Optional: a Frank Energie account, for personal prices and cost sensors

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=archofthings&repository=home-assistant-frank-energie&category=integration)

Or add it by hand:

1. In HACS, open the menu (⋮) and choose **Custom repositories**.
2. Add `https://github.com/archofthings/home-assistant-frank-energie` with type **Integration**.
3. Search for **Frank Energie**, download it, and restart Home Assistant.

Releases are currently published as **pre-releases**. If HACS doesn't offer the newest one, open the integration in HACS, choose **Redownload**, and select the version.

### Manual

1. Download `frank_energie.zip` from the [latest release](https://github.com/archofthings/home-assistant-frank-energie/releases).
2. Extract it into `config/custom_components/frank_energie/` in your Home Assistant configuration folder.
3. Restart Home Assistant.

## Configuration

[![Open your Home Assistant instance and start setting up Frank Energie.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=frank_energie)

1. Go to **Settings → Devices & services → Add integration** and search for **Frank Energie**.
2. Choose whether to log in with your Frank Energie account:
   - **Without login** you get the public market prices.
   - **With login** you get your personal contract prices, plus the monthly cost and invoice sensors. The first site on your account that is in delivery is selected automatically, and the entry is named after its address.
3. Individual sensors can be disabled or hidden afterwards.

If your login expires and can't be renewed automatically, Home Assistant asks you to **re-authenticate** from **Settings → Devices & services**.

> [!IMPORTANT]
> The old `configuration.yaml` setup is no longer supported. Remove any `frank_energie` YAML configuration and set the integration up through the UI.

## Sensors

Prices are fetched every hour. Sensor states switch at every quarter hour (:00, :15, :30, :45) to the price of the current 15-minute slot.

### Electricity (€/kWh)

| Sensor | Enabled by default | `prices` attribute |
|---|:---:|:---:|
| Current electricity price (All-in) | ✅ | ✅ |
| Current electricity market price | ✅ | ✅ |
| Current electricity price including tax | ✅ | ✅ |
| Current electricity VAT price | – | |
| Current electricity sourcing markup | – | |
| Current electricity tax only | – | |
| Lowest energy price today | ✅ | |
| Highest energy price today | ✅ | |
| Average electricity price today | ✅ | |

### Gas (€/m³)

| Sensor | Enabled by default | `prices` attribute |
|---|:---:|:---:|
| Current gas price (All-in) | ✅ | ✅ |
| Current gas market price | ✅ | ✅ |
| Current gas price including tax | ✅ | ✅ |
| Current gas VAT price | – | |
| Current gas sourcing price | – | |
| Current gas tax only | – | |
| Lowest gas price today | ✅ | |
| Highest gas price today | ✅ | |

The lowest and highest price sensors have a `from_time` attribute with the start of that slot.

### Costs (€, login required)

| Sensor | Description |
|---|---|
| Actual monthly cost | Costs so far this month, up to the last meter reading (`Last update` attribute) |
| Expected monthly cost until now | Expected costs up to the last meter reading |
| Expected cost this month | Expected costs for the whole month |
| Invoice previous period | Previous invoice (`Start date` and `Description` attributes) |
| Invoice current period | Current invoice period |
| Invoice upcoming period | Upcoming invoice |

A sensor shows as **unavailable** when there's no data for it, for example when gas prices are missing, or there's no month summary yet for a new account.

## Using the price list

The all-in, market and including-tax sensors have a `prices` attribute. It lists every known 15-minute slot for today and tomorrow:

```yaml
prices:
  - from: 2026-09-28T10:00:00+00:00
    till: 2026-09-28T10:15:00+00:00
    price: 0.245
  - from: 2026-09-28T10:15:00+00:00
    till: 2026-09-28T10:30:00+00:00
    price: 0.240
  # ...
```

Times are in UTC and prices are rounded to 3 decimals. With tomorrow's prices included the list holds up to 200 entries, so it's **not stored in the recorder history**, to stay within Home Assistant's attribute size limit. It is always available on the live state, in templates and in dashboards.

The examples below use `sensor.current_electricity_price_all_in`. Your entity ID may differ; check it under **Settings → Devices & services → Frank Energie**.

Highest price still to come:

```jinja
{{ state_attr('sensor.current_electricity_price_all_in', 'prices')
   | selectattr('from', 'gt', now()) | max(attribute='price') }}
```

Lowest price today:

```jinja
{{ state_attr('sensor.current_electricity_price_all_in', 'prices')
   | selectattr('from', 'ge', today_at('00:00'))
   | selectattr('till', 'le', today_at('00:00') + timedelta(days=1))
   | min(attribute='price') }}
```

Lowest price in the next six hours:

```jinja
{{ state_attr('sensor.current_electricity_price_all_in', 'prices')
   | selectattr('from', 'gt', now())
   | selectattr('till', 'lt', now() + timedelta(hours=6))
   | min(attribute='price') }}
```

## Charts

The price list can be plotted with [ApexCharts Card](https://github.com/RomRider/apexcharts-card).

### Today and tomorrow

![ApexCharts example: all prices](images/example_1.png "Today and tomorrow")

```yaml
type: custom:apexcharts-card
graph_span: 48h
span:
  start: day
now:
  show: true
  label: Now
header:
  show: true
  title: Electricity price per 15 minutes (€/kWh)
series:
  - entity: sensor.current_electricity_price_all_in
    show:
      legend_value: false
    stroke_width: 2
    float_precision: 3
    type: column
    opacity: 0.3
    color: '#03b2cb'
    data_generator: |
      return entity.attributes.prices.map((record) => [record.from, record.price]);
```

### Next hours

![ApexCharts example: next hours](images/example_2.png "Next hours")

```yaml
type: custom:apexcharts-card
graph_span: 14h
span:
  start: hour
  offset: '-3h'
now:
  show: true
  label: Now
header:
  show: true
  show_states: true
  colorize_states: true
yaxis:
  - decimals: 2
    min: 0
    max: '|+0.10|'
series:
  - entity: sensor.current_electricity_price_all_in
    show:
      in_header: raw
      legend_value: false
    stroke_width: 2
    float_precision: 4
    type: column
    opacity: 0.3
    color: '#03b2cb'
    data_generator: |
      return entity.attributes.prices.map((record) => [record.from, record.price]);
```

## Upgrading from the original integration

**Switching an existing HACS installation:**

1. In HACS, open **Frank Energie** and choose **Remove**. This removes the integration's files only; your configured integration, entities and history stay in Home Assistant.
2. Remove the old repository from **Custom repositories**: `https://github.com/bajansen/home-assistant-frank_energie`, or `https://github.com/archofthings/home-assistant-frank_energie` if you installed the earlier fork.
3. Add this repository and download it as described under [Installation](#installation).
4. Restart Home Assistant.

**What changes:**

- **Home Assistant 2026.9 or newer** is required.
- **Prices are per 15 minutes** instead of per hour. Automations and templates that assume hourly values, or 24 entries per day in `prices`, may need adjusting (a day now has 96 entries, or 92/100 on daylight-saving days).
- **Lowest and highest price today** now pick a 15-minute slot, so they can be more extreme than the old hourly values.
- **Existing entities keep their entity IDs and history**, because their unique IDs are unchanged.
- **The `prices` attribute is no longer stored in history**; see [Using the price list](#using-the-price-list).

## Troubleshooting

**HACS shows a download error (404).** The release has no `frank_energie.zip` attached. Pick a newer release in HACS.

**Sensors are unavailable.**
- *Just after midnight:* tomorrow's prices may not have been loaded yet. They're fetched hourly and normally published around 13:00.
- *Gas sensors:* if your contract has no gas, the gas sensors stay unavailable.

**Debug logging.** Add this to `configuration.yaml` and restart:

```yaml
logger:
  default: warning
  logs:
    custom_components.frank_energie: debug
    python_frank_energie: debug
```

> [!WARNING]
> Debug logs from `python_frank_energie` can contain your address and full price data. Remove personal details before sharing logs in an issue. The integration itself never logs your tokens or password.

Please report problems via [GitHub issues](https://github.com/archofthings/home-assistant-frank-energie/issues).

## Development

```text
custom_components/frank_energie/
├── __init__.py      # setup, delivery site discovery
├── config_flow.py   # UI setup, login and reauth
├── coordinator.py   # data fetching, fallbacks, token handling
├── sensor.py        # sensor definitions
└── manifest.json    # pins python-frank-energie==2026.9.20
tests/               # pytest-homeassistant-custom-component tests (API fully mocked)
```

Run the checks locally with Python 3.14:

```bash
python3.14 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
flake8 . --count --max-complexity=10 --max-line-length=120 --statistics
pytest
```

CI runs flake8 and pytest on every push and pull request. Publishing a GitHub release builds `frank_energie.zip` and attaches it to the release for HACS.

## Project history

This integration was created as [bajansen/home-assistant-frank_energie](https://github.com/bajansen/home-assistant-frank_energie) by [@bajansen](https://github.com/bajansen) and contributors, and was developed there until early 2025.

In 2026 Frank Energie changed its API, which broke the original integration. Development continued briefly in a GitHub fork (`archofthings/home-assistant-frank_energie`) and has since moved to this repository:

- moved to the new API (`python-frank-energie` 2026.9.20) and Frank Energie's 15-minute prices
- more robust error handling, automatic token renewal, and support for accounts without gas or outside the Netherlands
- a rewritten test suite and updated CI and release workflows

The full commit history of the original project is kept in this repository. The integration domain (`frank_energie`) and entity unique IDs are unchanged, so existing installations can switch to this repository without losing their entities or history (see [Upgrading from the original integration](#upgrading-from-the-original-integration)).

## Credits and license

- Original integration by [@bajansen](https://github.com/bajansen) and contributors.
- API client: [python-frank-energie](https://pypi.org/project/python-frank-energie/).

This project is not affiliated with or endorsed by Frank Energie.

The upstream project doesn't include a license file, so no license has been added here either.
