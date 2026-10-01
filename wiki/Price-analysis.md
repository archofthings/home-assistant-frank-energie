# Price analysis

The price analysis turns the electricity price list into things you can use directly: a level per slot, an on/off signal for cheap moments, and the cheapest block of the day. Turn it on with the **Price analysis** [sensor group](Configuration#sensor-groups); the settings are on [page 2 of the options](Configuration#options-page-2-price-analysis-settings).

It contains **two independent calculations**:

| | Price levels | Cheapest period |
|---|---|---|
| Question it answers | "Is the price cheap right now?" | "When is the best moment today?" |
| Based on | Fixed prices you set | The prices of the day, compared with each other |
| Result on an expensive day | Maybe no cheap slot at all | Still the best block of that day |
| Entities | Electricity price level, Cheap electricity price now | Cheapest electricity period now, Next cheapest electricity period |

Everything uses the **all-in** electricity price. Gas has no price analysis.

## 1. Price levels

Every slot gets one level:

| Level | Shown as | Rule |
|---|---|---|
| `expensive` | Expensive | Price **above** the expensive price |
| `cheap_solar` | Cheap + solar | Price **at or below** the cheap price, and the solar forecast is at or above the solar threshold |
| `cheap` | Cheap | Price **at or below** the cheap price |
| `normal` | Normal | Everything in between |

With the defaults (cheap €0.25, expensive €0.40):

| Price | Solar forecast | Level |
|---|---|---|
| €0.19 | 0.2 kWh/h | `cheap` |
| €0.19 | 2.1 kWh/h | `cheap_solar` |
| €0.25 | none | `cheap` |
| €0.31 | 2.1 kWh/h | `normal` |
| €0.40 | none | `normal` |
| €0.41 | none | `expensive` |

### Solar forecast

Optional. Choose an integration under **Solar forecast** and cheap slots with enough expected production are marked `cheap_solar`. Use it to tell "cheap from the grid" apart from "cheap and my panels are producing".

- Works with every integration that provides a solar forecast to the Energy dashboard, such as Forecast.Solar and Solcast.
- The forecast is converted to **kWh per hour** for every slot, so the threshold means the same for quarter-hour and hourly prices. A quarter with a forecast of 0.5 kWh counts as 2.0 kWh/h.
- If the forecast integration is unavailable or slow, the analysis continues without solar: slots are then `cheap` instead of `cheap_solar`.
- Only cheap slots can become `cheap_solar`. A normal or expensive slot never does, however sunny.

## 2. Cheapest period

The **consecutive block** of the length you chose with the **lowest average price**. It is calculated three times:

| Calculation | Searches in | Used by |
|---|---|---|
| Today | Today's slots | *Cheapest electricity period now*, *Electricity price analysis today* |
| Tomorrow | Tomorrow's slots (once published) | *Electricity price analysis tomorrow* |
| From now on | All slots that have not ended yet, today and tomorrow | *Next cheapest electricity period* |

Details:

- The length is 15 minutes to 6 hours. With hourly prices it is rounded up to whole hours: 90 minutes becomes 2 hours.
- If two blocks have the same average price, the earliest one wins.
- The block is always one piece; it is never split in two.
- *Next cheapest electricity period* stays the same while that period is running. It only moves to a new period when the current one has ended or new prices arrive.

### Only when cheap

By default *Cheapest electricity period now* turns on during the cheapest period of **every** day, even when that day is expensive. Tick **Only when cheap** to let it turn on only when the period's average price is at or below your cheap price.

| Day | Cheapest 2 hours average | Only when cheap off | Only when cheap on |
|---|---|---|---|
| Sunny Sunday | €0.12 | On during the period | On during the period |
| Dark winter day | €0.34 | On during the period | Stays off |

## Entities

| Entity | State | Use it for |
|---|---|---|
| **Electricity price level** (`sensor`) | Level of the current slot | Conditions, colours on a dashboard |
| **Cheap electricity price now** (`binary_sensor`) | On while the current slot is `cheap` or `cheap_solar` | Run something whenever it is cheap |
| **Cheapest electricity period now** (`binary_sensor`) | On during today's cheapest period | Run something once a day for a fixed time |
| **Next cheapest electricity period** (`sensor`) | Start time of the cheapest period from now on | Planning, "starts in…" on a dashboard |
| **Electricity price analysis today** (`sensor`) | Start time of today's cheapest period | Charts, templates |
| **Electricity price analysis tomorrow** (`sensor`) | Start time of tomorrow's cheapest period | Charts, templates |

All of them refresh at every quarter hour and whenever new prices arrive.

### Attributes of *Electricity price level*

| Attribute | Meaning |
|---|---|
| `cheap_threshold` | Your cheap price |
| `expensive_threshold` | Your expensive price |

### Attributes of *Next cheapest electricity period*

| Attribute | Meaning |
|---|---|
| `end` | End of the period |
| `average_price` | Average all-in price in the period |
| `minutes` | Length of the period |

### Attributes of *Electricity price analysis today / tomorrow*

Made for charts and templates. Not stored in history.

| Attribute | Meaning |
|---|---|
| `slots` | One entry per price slot, see below |
| `cheapest_period` | The cheapest period of that day: `start`, `end`, `average_price`, `minutes` |
| `cheap_windows` | List of blocks of consecutive cheap (and cheap + solar) slots |
| `expensive_windows` | List of blocks of consecutive expensive slots |
| `solar_windows` | List of blocks of consecutive cheap + solar slots, with `average_solar_kwh` |
| `thresholds` | Your settings: `cheap`, `expensive`, `solar_kwh` |

Every window has `start`, `end`, `average_price` and `minutes`.

Every entry in `slots`:

| Key | Meaning |
|---|---|
| `from`, `till` | Start and end of the slot |
| `price` | All-in price |
| `level` | `cheap_solar`, `cheap`, `normal` or `expensive` |
| `solar_kwh` | Solar forecast for the slot in kWh per hour (0 without a forecast) |
| `in_cheapest_period` | `true` when the slot is part of that day's cheapest period |
| `is_current` | `true` for the slot of this moment |

```yaml
slots:
  - from: "2026-10-01T13:00:00+02:00"
    till: "2026-10-01T14:00:00+02:00"
    price: 0.1874
    level: cheap_solar
    solar_kwh: 2.31
    in_cheapest_period: true
    is_current: false
cheapest_period:
  start: "2026-10-01T13:00:00+02:00"
  end: "2026-10-01T15:00:00+02:00"
  average_price: 0.1902
  minutes: 120
cheap_windows:
  - start: "2026-10-01T11:00:00+02:00"
    end: "2026-10-01T16:00:00+02:00"
    average_price: 0.2105
    minutes: 300
thresholds:
  cheap: 0.25
  expensive: 0.4
  solar_kwh: 1.5
```

## Template examples

```jinja
{# When does today's cheapest period start? #}
{{ states('sensor.frank_energie_prices_electricity_price_analysis_today') | as_datetime | as_local }}

{# How many hours are cheap today? #}
{{ state_attr('sensor.frank_energie_prices_electricity_price_analysis_today', 'cheap_windows')
   | sum(attribute='minutes') / 60 }}

{# Minutes until the next cheapest period starts #}
{{ ((states('sensor.frank_energie_prices_next_cheapest_electricity_period') | as_datetime - now()).total_seconds() / 60) | round }}

{# Is the next hour expensive? #}
{{ state_attr('sensor.frank_energie_prices_electricity_price_analysis_today', 'slots')
   | selectattr('from', 'gt', now())
   | map(attribute='level') | first == 'expensive' }}
```

More: [Automation examples](Automation-examples) and the [Chart gallery](Chart-gallery).

## Choosing your prices

- **Cheap price:** look at a week of prices and pick the price below which you would gladly charge a battery or run the dishwasher. A common start is your average price minus a few cents.
- **Expensive price:** the price above which you want to avoid using power, for example to stop charging or to discharge a home battery.
- Prices change with the seasons; check the two prices a few times a year.
- Want a signal that works on every day without tuning? Use the **cheapest period** instead of the levels.
