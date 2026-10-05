# Sensors

Every entity of the integration, per [sensor group](Configuration#sensor-groups), with its state and attributes.

- [General behaviour](#general-behaviour)
- [Current prices](#current-prices) (always on)
- [Daily statistics](#daily-statistics)
- [Upcoming and tomorrow prices](#upcoming-and-tomorrow-prices)
- [Price analysis](#price-analysis)
- [Costs and invoices](#costs-and-invoices) 🔑
- [Daily usage and costs](#daily-usage-and-costs) 🔑
- [Monthly usage and costs](#monthly-usage-and-costs) 🔑
- [Energy dashboard statistics](#energy-dashboard-statistics) 🔑
- [Feed-in price](#feed-in-price)

🔑 = only when logged in.

Entity IDs below are those of a new installation, see [About entity IDs](Home#about-entity-ids-on-this-wiki). Price entities start with `sensor.frank_energie_prices_`, account entities with `sensor.frank_energie_costs_`.

## General behaviour

- **Units:** electricity prices in €/kWh, gas prices in €/m³, all including what the sensor name says. "All-in" is the price you pay: market price + VAT + sourcing markup + energy tax.
- **A price slot** is one quarter-hour or one hour, depending on your [price resolution](Configuration#price-resolution).
- **State updates:** price sensors switch to the current slot at every quarter hour (:00, :15, :30, :45).
- **Unavailable** means there is no data for that sensor right now, for example the tomorrow sensors before tomorrow's prices are published (usually around 13:00).
- **Times in attributes** follow the [time zone option](Configuration#time-zone-for-price-times).
- **Large attributes are not stored in history:** `prices`, `hours`, `slots` and the window lists exist only on the live state. Use them in templates, charts and automations; they are not available in the history of the entity.
- **Days and months** are those of Frank Energie's market: the Dutch calendar (Europe/Amsterdam), whatever the time zone of your Home Assistant.

## Current prices

Always created, for electricity and gas. Device: *Frank Energie - Prices*.

| Name | Entity ID ends with | State | Enabled by default |
|---|---|---|---|
| Current electricity price (All-in) | `current_electricity_price_all_in` | All-in price of the current slot | Yes |
| Current electricity market price | `current_electricity_market_price` | Market price, without tax and markup | Yes |
| Current electricity price including tax | `current_electricity_price_including_tax` | Market price + VAT | Yes |
| Current electricity VAT price | `current_electricity_vat_price` | VAT part of the price | No |
| Current electricity sourcing markup | `current_electricity_sourcing_markup` | Frank Energie's markup | No |
| Current electricity tax only | `current_electricity_tax_only` | Energy tax part of the price | No |
| Current gas price (All-in) | `current_gas_price_all_in` | All-in gas price now | Yes |
| Current gas market price | `current_gas_market_price` | Market price, without tax and markup | Yes |
| Current gas price including tax | `current_gas_price_including_tax` | Market price + VAT | Yes |
| Current gas VAT price | `current_gas_vat_price` | VAT part of the price | No |
| Current gas sourcing price | `current_gas_sourcing_price` | Frank Energie's markup | No |
| Current gas tax only | `current_gas_tax_only` | Energy tax part of the price | No |

Enable the disabled ones under **Settings → Devices & services → Frank Energie → entities**.

### Attribute `prices`

The **All-in**, **market price** and **including tax** sensors (electricity and gas) have a `prices` attribute: every known slot of today and tomorrow, with the price of that sensor.

```yaml
prices:
  - from: "2026-10-01T00:00:00+02:00"
    till: "2026-10-01T00:15:00+02:00"
    price: 0.243
  - from: "2026-10-01T00:15:00+02:00"
    till: "2026-10-01T00:30:00+02:00"
    price: 0.239
```

| Key | Meaning |
|---|---|
| `from` | Start of the slot |
| `till` | End of the slot |
| `price` | The price in that slot (3 decimals): all-in, market or including tax, depending on the sensor |

See [Price list and get_prices action](Price-list-and-get_prices-action) for examples.

## Daily statistics

Group **Daily statistics**. Device: *Frank Energie - Prices*.

| Name | Entity ID ends with | State | Attributes |
|---|---|---|---|
| Lowest energy price today | `lowest_energy_price_today` | Lowest all-in electricity price of today | `from_time` |
| Highest energy price today | `highest_energy_price_today` | Highest all-in electricity price of today | `from_time` |
| Average electricity price today | `average_electricity_price_today` | Average all-in electricity price of today | |
| Lowest gas price today | `lowest_gas_price_today` | Lowest all-in gas price of today | `from_time` |
| Highest gas price today | `highest_gas_price_today` | Highest all-in gas price of today | `from_time` |

`from_time` is the start of the slot with that price.

## Upcoming and tomorrow prices

Group **Upcoming and tomorrow prices**. Device: *Frank Energie - Prices*.

| Name | Entity ID ends with | State | Attributes |
|---|---|---|---|
| Next electricity price (All-in) | `next_electricity_price_all_in` | All-in price of the next slot | `from_time` |
| Average electricity price tomorrow | `average_electricity_price_tomorrow` | Average all-in price of tomorrow | |
| Lowest electricity price tomorrow | `lowest_electricity_price_tomorrow` | Lowest all-in price of tomorrow | `from_time` |
| Highest electricity price tomorrow | `highest_electricity_price_tomorrow` | Highest all-in price of tomorrow | `from_time` |
| Lowest upcoming electricity price | `lowest_upcoming_electricity_price` | Lowest all-in price still to come (today and tomorrow) | `from_time` |
| Highest upcoming electricity price | `highest_upcoming_electricity_price` | Highest all-in price still to come | `from_time` |
| Average gas price tomorrow | `average_gas_price_tomorrow` | Average all-in gas price of tomorrow | |
| Tomorrow's prices available | `binary_sensor.frank_energie_prices_tomorrow_s_prices_available` | **On** once tomorrow's electricity prices are known; off again after midnight | `date` (the day the prices are for, only while on) |

The tomorrow sensors are **unavailable** until tomorrow's prices are published. *Tomorrow's prices available* is a handy trigger: it turns on at the moment the prices arrive. See [Automation examples](Automation-examples#notify-when-tomorrows-prices-arrive).

## Price analysis

Group **Price analysis**. Device: *Frank Energie - Prices*. Explained in detail on the [Price analysis](Price-analysis) page.

| Name | Entity ID | State | Attributes |
|---|---|---|---|
| Electricity price level | `sensor.frank_energie_prices_electricity_price_level` | `cheap_solar`, `cheap`, `normal` or `expensive` for the current slot | `cheap_threshold`, `expensive_threshold` |
| Cheap electricity price now | `binary_sensor.frank_energie_prices_cheap_electricity_price_now` | On while the current slot is cheap or cheap + solar | |
| Cheapest electricity period now | `binary_sensor.frank_energie_prices_cheapest_electricity_period_now` | On during today's cheapest period | |
| Next cheapest electricity period | `sensor.frank_energie_prices_next_cheapest_electricity_period` | Start time of the cheapest period from now on | `end`, `average_price`, `minutes` |
| Electricity price analysis today | `sensor.frank_energie_prices_electricity_price_analysis_today` | Start time of today's cheapest period | `slots`, `cheapest_period`, `cheap_windows`, `expensive_windows`, `solar_windows`, `thresholds` |
| Electricity price analysis tomorrow | `sensor.frank_energie_prices_electricity_price_analysis_tomorrow` | Start time of tomorrow's cheapest period (unavailable until published) | The same |

## Costs and invoices

Group **Costs and invoices** 🔑. Device: *Frank Energie - Costs*. Amounts in €.

| Name | Entity ID ends with | State | Attributes |
|---|---|---|---|
| Actual monthly cost | `actual_monthly_cost` | Your actual costs this month, up to the last meter reading | `Last update` (date of the last meter reading) |
| Expected monthly cost until now | `expected_monthly_cost_until_now` | What Frank Energie expected you to have spent up to the last meter reading | `Last update` |
| Monthly cost difference until now | `monthly_cost_difference_until_now` | Actual minus expected costs up to the last meter reading; negative when you pay less than expected | `Last update` |
| Expected cost this month | `expected_cost_this_month` | Expected costs for the whole month | |
| Invoice previous period | `invoice_previous_period` | Total of the previous invoice | `Start date`, `Description` |
| Invoice current period | `invoice_current_period` | Total of the current invoice | `Start date`, `Description` |
| Invoice upcoming period | `invoice_upcoming_period` | Total of the upcoming invoice | `Start date`, `Description` |
| Total this year | `total_this_year` | Sum of all invoices of this calendar year | `invoices` |
| Total last year | `total_last_year` | Sum of all invoices of last calendar year | `invoices` |
| Price resolution | `price_resolution` | `pt15m` (15 minutes) or `pt60m` (hourly) | See below |

Comparing *Actual monthly cost* with *Expected monthly cost until now* tells you whether you are spending more or less than expected.

An invoice sensor is unavailable when Frank Energie has no invoice for that period.

### Attribute `invoices`

On *Total this year* and *Total last year*: one entry per invoice period, oldest first. Invoices for the same period, such as a correction invoice, are added together.

```yaml
invoices:
  - start_date: "2026-08-01"
    description: "Augustus 2026"
    total_amount: 87.31
  - start_date: "2026-09-01"
    description: "September 2026"
    total_amount: 92.04
```

An invoice counts for the year its period starts in.

### Price resolution

Shows the price resolution of your **contract**. Read-only: changing it is done with Frank Energie.

| Attribute | Meaning |
|---|---|
| `available_options` | The resolutions your contract can have |
| `is_change_request_possible` | Whether Frank Energie currently accepts a change request |
| `upcoming_change` | A change that is already planned, if any |
| `upcoming_change_effective_date` | When that planned change starts |
| `change_request_effective_date` | When a new change request would start |

Unavailable when your account has no electricity connection.

## Daily usage and costs

Group **Daily usage and costs** 🔑. Device: *Frank Energie - Costs*.

| Name | Entity ID ends with | Unit |
|---|---|---|
| Electricity usage yesterday | `electricity_usage_yesterday` | kWh |
| Electricity costs yesterday | `electricity_costs_yesterday` | € |
| Gas usage yesterday | `gas_usage_yesterday` | m³ |
| Gas costs yesterday | `gas_costs_yesterday` | € |
| Feed-in yesterday | `feed_in_yesterday` | kWh |
| Feed-in revenue yesterday | `feed_in_revenue_yesterday` | € |

| Attribute | Meaning |
|---|---|
| `date` | The day the numbers are for |
| `hours` | Per hour: `from`, `till`, `usage` and `costs` |

```yaml
date: "2026-09-30"
hours:
  - from: "2026-09-30T00:00:00+02:00"
    till: "2026-09-30T01:00:00+02:00"
    usage: 0.412
    costs: 0.098
```

Good to know:

- The sensors show **yesterday**, because Frank Energie receives smart meter data a day later.
- In Home Assistant's long-term statistics each day's value therefore lands **one day late**. For the Energy dashboard use the [Energy dashboard statistics](Energy-dashboard-statistics) group, which puts every hour at the right time.
- Gas sensors are only created when your account has gas; feed-in sensors only when it has feed-in.
- Feed-in and feed-in revenue are **positive** numbers.
- Refreshed every 3 hours.

## Monthly usage and costs

Group **Monthly usage and costs** 🔑. Device: *Frank Energie - Costs*.

| Name | Entity ID ends with | Unit | Attributes |
|---|---|---|---|
| Electricity usage this month | `electricity_usage_this_month` | kWh | `expected_usage`, `last_meter_reading` |
| Electricity costs this month | `electricity_costs_this_month` | € | `expected_costs`, `average_price`, `last_meter_reading` |
| Gas usage this month | `gas_usage_this_month` | m³ | `expected_usage`, `last_meter_reading` |
| Gas costs this month | `gas_costs_this_month` | € | `expected_costs`, `average_price`, `last_meter_reading` |
| Feed-in this month | `feed_in_this_month` | kWh | `expected_usage`, `last_meter_reading` |
| Feed-in revenue this month | `feed_in_revenue_this_month` | € | `expected_costs`, `average_price`, `last_meter_reading` |
| Fixed costs this month (expected) | `fixed_costs_this_month_expected` | € | `last_meter_reading` |
| Fixed costs this month until now | `fixed_costs_this_month_until_now` | € | `last_meter_reading` |

| Attribute | Meaning |
|---|---|
| `expected_usage` | The usage Frank Energie expected |
| `expected_costs` | The costs Frank Energie expected |
| `average_price` | Your average price per kWh or m³ this month |
| `last_meter_reading` | Date of the last meter reading the numbers include |

Good to know:

- The numbers run **up to the last meter reading**, usually yesterday.
- On the **1st of the month** these sensors can be unavailable until Frank Energie has meter readings for the new month.
- Gas and feed-in sensors are only created when your account has them. Feed-in and revenue are positive numbers.
- Refreshed every 3 hours.

## Energy dashboard statistics

Group **Energy dashboard statistics** 🔑. This group creates **no entities**. It imports six long-term statistics that you can pick in the Energy dashboard and in statistics cards. See [Energy dashboard statistics](Energy-dashboard-statistics).

## Feed-in price

Group **Feed-in price** (version 1.8.4 or newer). No login needed. Off by default. Device: *Frank Energie - Prices*.

| Name | Entity ID ends with | State | Attributes |
|---|---|---|---|
| Current electricity feed-in price | `current_electricity_feed_in_price` | The price you receive per kWh for electricity returned to the grid, in the current slot | `prices`: every slot with `from`, `till` and `price`, like the other price sensors |

Use it in the Energy dashboard under *Return to grid* → **Use an entity with current price**, see [Energy dashboard statistics](Energy-dashboard-statistics#live-feed-in-price).

### Settings

On the *Feed-in price settings* page of **Configure** (shown when the group is ticked), see [Configuration](Configuration#feed-in-price-settings):

| Setting | Meaning | Default |
|---|---|---|
| **Feed-in markup (€/kWh)** | The *Inkoopvergoeding teruglevering* on your contract letter, including VAT. Usually negative. | -0.01271 |
| **Smart feed-in** | Adds Frank Energie's 15% Smart feed-in bonus to positive prices | Off |

### How the price is calculated

- Feed-in price = market price including VAT (+15% when *Smart feed-in* is on and the price is positive) + feed-in markup.
- Example with a market price including VAT of 0.10 and a markup of -0.01271: 0.08729 without and 0.10229 with Smart feed-in. A negative price gets no bonus: -0.05 becomes -0.06271.

### Limits

- Frank Energie does not provide this price. The markup comes from your own contract letter and can differ per contract.
- The netted energy tax (*salderen*, until 1 January 2027) is not included, so the sensor matches the feed-in revenue Frank Energie reports per hour.
- The Smart feed-in bonus follows Frank Energie's announced 15%. How it is applied has not been checked against real invoices.
- From 1 January 2027 Frank Energie's feed-in tariff changes, so the calculation may need an update.
