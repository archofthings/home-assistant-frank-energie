# Frank Energie for Home Assistant

A Home Assistant custom integration for [Frank Energie](https://www.frankenergie.nl/): electricity and gas prices per quarter-hour or per hour, a price analysis for automations and charts, and optionally your own usage, costs and invoices.

![Today's prices coloured by level, with the Sell line and the solar forecast](https://raw.githubusercontent.com/archofthings/home-assistant-frank-energie/main/images/prices_today.png)

## Where to start

| I want to… | Page |
|---|---|
| Install the integration | [Installation](Installation) |
| Log in, choose an address, change settings | [Configuration](Configuration) |
| Know what every sensor and attribute means | [Sensors](Sensors) |
| Label prices as cheap or expensive and find the cheapest hours | [Price analysis](Price-analysis) |
| See Frank Energie's usage and costs in the Energy dashboard | [Energy dashboard statistics](Energy-dashboard-statistics) |
| Read the full price list in a template, script or automation | [Price list and get_prices action](Price-list-and-get_prices-action) |
| Copy a chart for my dashboard | [Chart gallery](Chart-gallery) |
| Copy an automation | [Automation examples](Automation-examples) |
| Understand when data is fetched and what happens on errors | [How it works](How-it-works) |
| Fix a problem | [Troubleshooting](Troubleshooting) |
| Move from the original integration | [Upgrading](Upgrading) |
| Work on the code | [Development](Development) |

## What you get

| | Without an account | With your Frank Energie login |
|---|---|---|
| Electricity and gas prices (all-in, market, tax, VAT, markup) | Public prices | Your contract's prices |
| Price resolution | Quarter-hour or hour, your choice | The resolution of your contract |
| Daily statistics, upcoming and tomorrow prices | ✓ | ✓ |
| Price analysis (levels, cheapest period, chart data) | ✓ | ✓ |
| `frank_energie.get_prices` action | ✓ | ✓ |
| Monthly costs, invoices, yearly totals | | ✓ |
| Yesterday's and this month's usage, costs and feed-in | | ✓ |
| Energy dashboard statistics (hourly usage and costs) | | ✓ |
| [Feed-in price](Sensors#feed-in-price) sensor (off by default, version 1.8.4) | ✓ | ✓ |
| Choice of delivery address | | ✓ |

## Requirements

- Home Assistant **2026.9** or newer.
- [HACS](https://hacs.xyz/) for the easiest installation (a manual install also works).
- For the charts: [ApexCharts Card](https://github.com/RomRider/apexcharts-card) (optional).
- For "cheap + solar": an integration that provides a solar forecast to the Energy dashboard, such as Forecast.Solar or Solcast (optional).

## About entity IDs on this wiki

Entity IDs on this wiki are those of a **new installation** with Home Assistant in English, for example `sensor.frank_energie_prices_current_electricity_price_all_in`. Yours can differ:

- Installations upgraded from the original integration keep their older IDs without the `frank_energie_prices_` prefix.
- If you renamed an entity, its ID is whatever you chose.

Find your own IDs under **Settings → Devices & services → Frank Energie**.

---

## Credits

- **[@HiDiHo01](https://github.com/HiDiHo01)** maintains [python-frank-energie](https://github.com/HiDiHo01/python-frank-energie), the API client this integration uses for all communication with Frank Energie.
- **[@bajansen](https://github.com/bajansen)** and the contributors of the original integration, [bajansen/home-assistant-frank_energie](https://github.com/bajansen/home-assistant-frank_energie), which this project continues.

Not affiliated with or endorsed by Frank Energie.
