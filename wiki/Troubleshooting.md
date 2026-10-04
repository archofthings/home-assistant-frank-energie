# Troubleshooting

- [Sensors](#sensors)
- [Login and setup](#login-and-setup)
- [Options](#options)
- [Price analysis](#price-analysis)
- [Usage, costs and statistics](#usage-costs-and-statistics)
- [Known issues](#known-issues)
- [Charts](#charts)
- [Log messages](#log-messages)
- [Diagnostics](#diagnostics)
- [Debug logging](#debug-logging)
- [Report a problem](#report-a-problem)

## Sensors

| Problem | Cause and solution |
|---|---|
| Tomorrow sensors are unavailable | Normal until tomorrow's prices are published, usually around 13:00. |
| Gas sensors are unavailable | No gas prices are known. Check again after the next update. |
| A sensor I expect does not exist | Its [sensor group](Configuration#sensor-groups) is off, or it needs a login. Some price sensors (VAT, markup, tax only) exist but are disabled by default. |
| No gas or feed-in usage sensors | They are only created when your account has gas or feed-in data. |
| All sensors are unavailable | Frank Energie could not be reached and there are no usable prices left. Check the log; the integration retries by itself. |
| Sensors of a group disappeared | The group was unticked under **Configure**. Tick it again: the entities come back with the same IDs and history. |
| Today's lowest or highest price differs from the Frank Energie app | Check the resolution: quarter-hour prices are more extreme than hourly averages. Also compare the same kind of price (all-in). |
| Prices are not those of my contract | The entry is not logged in and shows public prices. Remove it and add it again with your account. |
| The `prices` attribute is not in the history | By design: large attributes are only on the live state. See [Sensors](Sensors#general-behaviour). |
| Entity IDs differ from this wiki | See [About entity IDs](Home#about-entity-ids-on-this-wiki). |

## Login and setup

| Problem | Cause and solution |
|---|---|
| *Credentials rejected* | Check the e-mail address and password in the Frank Energie app or website. |
| *Failed to connect* | Frank Energie's service can't be reached. Try again later. |
| *No active delivery address was found* | The account has no address in delivery (contract not started yet or ended). |
| *Account is already configured* | This account already has an entry. Use **Reconfigure** to choose another address. |
| *The account you logged in with differs…* | During re-authentication you must use the same account. Add the other account as a new integration. |
| **Reconfigure** says it is not available | The entry has no login, so there is no address to choose. |
| Home Assistant keeps asking to re-authenticate | Log in again. If it returns, [report it](#report-a-problem) with diagnostics. |
| The integration is not in the list | Restart Home Assistant after installing through HACS, and refresh your browser. |

## Options

| Problem | Cause and solution |
|---|---|
| No **Price resolution** option | You are logged in: prices follow your contract. See [Price resolution](Configuration#price-resolution). |
| Costs or usage groups are not in the list | Those groups need a login. |
| No second page with analysis settings | Tick **Price analysis** on page 1 first. |
| The **Solar forecast** list is empty | No integration with a solar forecast for the Energy dashboard is installed. |
| *The cheap price threshold must be lower…* | Enter a cheap price below the expensive price. |
| Times in attributes jumped by one or two hours | The [time zone option](Configuration#time-zone-for-price-times) changed. The moments are the same; fix flows that read the time as text. |

## Price analysis

| Problem | Cause and solution |
|---|---|
| *Cheapest electricity period now* never turns on | **Only when cheap** is ticked and the cheapest period is more expensive than your cheap price. Untick it or raise the cheap price. |
| Nothing is ever `cheap` | Your cheap price is below the prices of the day. Raise it in the [options](Configuration#options-page-2-price-analysis-settings). |
| No `cheap_solar` level | No solar forecast is chosen, the forecast is below the threshold, or the slot is not cheap. Check `solar_kwh` in the `slots` attribute. |
| `solar_kwh` is always 0 | The solar integration gives no forecast. Check that it works in the Energy dashboard. |
| The cheapest period is longer than I set | With hourly prices the length is rounded up to whole hours. |
| *Electricity price analysis tomorrow* is unavailable | Normal until tomorrow's prices are published. |

## Usage, costs and statistics

| Problem | Cause and solution |
|---|---|
| Cost, invoice or monthly usage sensors unavailable while prices work | Frank Energie's service for that data is failing. Prices keep updating and the sensors come back by themselves. |
| Monthly usage sensors unavailable on the 1st | Frank Energie has no meter readings for the new month yet. They come back by themselves, usually within a day. |
| Daily sensors show yesterday | By design: Frank Energie receives meter data a day later. |
| Usage sensors stay unavailable | Your meter may not share data with Frank Energie. Check whether the Frank Energie app shows your usage. |
| The Energy dashboard shows nothing for today | Frank Energie's data arrives a day later. See [Energy dashboard statistics](Energy-dashboard-statistics#use-it-in-the-energy-dashboard). |
| Statistics do not appear | The first import takes a few minutes. Then search for `frank_energie:` under **Developer tools → Statistics**. |
| Days are missing in the statistics | Frank Energie has no data for those days. |
| Numbers differ from my own meter | The statistics are Frank Energie's numbers. Small differences with a P1 reader are normal. |
| An invoice sensor is unavailable | There is no invoice for that period (yet). |

## Known issues

These are caused by Frank Energie's service, not by the integration, and can't be solved in Home Assistant.

| Issue | Explanation |
|---|---|
| Expected and actual monthly costs are a day behind the daily and monthly usage and costs (or the other way around) | Frank Energie publishes these numbers separately, sometimes hours apart. The integration refreshes all cost data as soon as one of them has a new day (see [Update schedule](How-it-works#update-schedule)), but it can only show what Frank Energie has published. They match again once Frank Energie has published everything, usually the same day. |
| The costs chart from the statistics is a day behind the cost sensors | Same cause: the hourly usage and costs for that day are not published yet. The next import adds them. |

## Charts

| Problem | Cause and solution |
|---|---|
| The card stays on "Loading" | A series returns `null` values or is an `area` series. Use the cards from the [Chart gallery](Chart-gallery) as they are. |
| The card shows nothing at all | The pasted `data_generator` is incomplete. Paste the whole card again. |
| *Custom element doesn't exist: apexcharts-card* | Install [ApexCharts Card](https://github.com/RomRider/apexcharts-card) through HACS and refresh the browser. |
| Columns are shifted half a slot | Use `30 * 60 * 1000` for hourly prices and `7.5 * 60 * 1000` for quarter-hour prices. |
| Columns are very narrow | Use one column series with a colour per column, not a series per colour. |
| Columns are cut off at the top | Raise `max` of the price axis. |
| Entity not available in the card | The entity ID differs or the sensor group is off. |
| The tomorrow chart is empty | Normal until tomorrow's prices are published. |
| A statistics card is empty | Replace `YOUR_SITE` with your own statistic ID. |

## Log messages

Find them under **Settings → System → Logs**.

| Message | Meaning |
|---|---|
| `Could not fetch month_summary, keeping the previous value` | Monthly costs failed this time. Prices are not affected. |
| `Could not fetch invoices, keeping the previous value` | Invoices failed this time. Prices are not affected. |
| `Could not update daily usage and costs, using previous data` | Yesterday's usage failed this time. |
| `Could not update monthly usage and costs, using previous data` | This month's usage failed this time. Normal on the 1st of the month. |
| `Could not fetch usage and costs for …, stopping the import` | The statistics import stopped at that day and continues at the next run. |
| `The recorder is not loaded, not importing Energy dashboard statistics` | Enable Home Assistant's recorder. |
| `Could not merge today's and tomorrow's prices` | Today's and tomorrow's prices have a different form, for example on the day your contract's price resolution changes. Tomorrow's prices are left out until the next day. |
| `Failed to renew token … Starting user reauth flow` | Log in again, see [Re-authenticate](Configuration#re-authenticate). |
| `No user prices available, falling back to public prices` | Your account has no contract prices for that day; public prices are used. |

A warning that returns for a short time is harmless. If it stays for more than a day, [report it](#report-a-problem).

## Diagnostics

**Settings → Devices & services → Frank Energie** → menu (⋮) → **Download diagnostics**.

The file contains the state of the integration: your sensor groups, when data was last fetched, the last error, the number of price slots and whether costs, usage and contract data are available. It contains **no** prices or usage numbers. Tokens, e-mail address, entry name, site reference and connection ID are removed.

## Debug logging

Turn it on under **Settings → Devices & services → Frank Energie** → menu (⋮) → **Enable debug logging**, reproduce the problem and turn it off again to download the log. Or in `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.frank_energie: debug
    python_frank_energie: debug
```

> [!WARNING]
> The library's debug log can contain your address and price data. Remove personal details before sharing. The integration never logs tokens or passwords.

## Report a problem

Open a [GitHub issue](https://github.com/archofthings/home-assistant-frank-energie/issues) with:

1. The version of the integration and of Home Assistant.
2. What you expected and what happened.
3. The diagnostics file.
4. The relevant log lines.
