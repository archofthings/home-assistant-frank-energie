# Chart gallery

Ready-to-use dashboard cards. Add a card with **Edit dashboard → Add card → Manual** and paste the YAML.

**Prices**
- [Today's prices](#todays-prices)
- [Today and tomorrow](#today-and-tomorrow)
- [The next 12 hours](#the-next-12-hours)
- [Gas price, today and tomorrow](#gas-price-today-and-tomorrow)
- [Current price gauge](#current-price-gauge)
- [Price overview](#price-overview)
- [Upcoming prices as a table](#upcoming-prices-as-a-table)
- [Price history](#price-history)

**Price analysis**
- [Analysis today](#analysis-today)
- [Analysis tomorrow](#analysis-tomorrow)
- [Analysis today and tomorrow in one chart](#analysis-today-and-tomorrow-in-one-chart)
- [Cheapest period card](#cheapest-period-card)

**Usage and costs** 🔑
- [Yesterday per hour](#yesterday-per-hour)
- [Costs per day](#costs-per-day)
- [Usage and feed-in per day](#usage-and-feed-in-per-day)
- [Costs per month](#costs-per-month)
- [Usage per month](#usage-per-month)
- [Invoices per month, this year and last year](#invoices-per-month-this-year-and-last-year)
- [This month: actual and expected](#this-month-actual-and-expected)
- [This month at a glance](#this-month-at-a-glance)
- [Cost breakdown this month](#cost-breakdown-this-month)
- [Month chart with navigation](#month-chart-with-navigation)
- [Real and saved costs per month](#real-and-saved-costs-per-month)

## Before you start

| Cards marked | Need |
|---|---|
| **ApexCharts** | The [ApexCharts Card](https://github.com/RomRider/apexcharts-card) from HACS |
| **Mushroom** | The [Mushroom cards](https://github.com/piitaya/lovelace-mushroom) from HACS, version 5 or newer |
| **Built-in** | Nothing extra |

Each card says which [sensor group](Configuration#sensor-groups) it needs. Replace the entity IDs with yours if they differ, see [About entity IDs](Home#about-entity-ids-on-this-wiki).

### Tips for the ApexCharts cards

- **Hourly or quarter-hour prices:** the cards use `30 * 60 * 1000` (half an hour) to centre the columns on **hourly** prices. With **quarter-hour** prices change it to `7.5 * 60 * 1000`, in the `data_generator` lines and in the tooltip.
- **Scale:** set `max` of the price axis to a little above your highest price, and `max` of the solar axis to your peak production in kWh per hour.
- Use **one** column series with colours per column; a separate series per colour makes the columns very narrow.
- Don't return `null` values and don't use an `area` series; the card then stays on "Loading".
- When you change a card: a series returns either `[time, value]` pairs, or `{ x, y, fillColor }` objects for coloured columns. Use the objects only on an axis with a fixed `min` and `max`; on an automatic axis the card stays on "Loading".
- If a card shows nothing at all, check that the pasted `data_generator` code is complete. One cut-off line stops the whole card.
- **Stacked columns:** leave out the card's own `yaxis:` list and set the axis under `apex_config`; with a `yaxis:` list the columns stand next to each other. Give every series one value per day or month (0 where there is no data), otherwise the columns become very thin.
- A card with `update_interval` only reloads on that timer and ignores changes of its entity. Leave it out when a helper should switch the chart.
- The tooltip uses Dutch date notation (`nl-NL`); change it to your own, for example `en-GB`.

---

# Prices

## Today's prices

**ApexCharts.** Needs: nothing extra (works without the price analysis). Columns are coloured with two prices you set in the card itself.

<details>
<summary>Show YAML</summary>

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Electricity prices today
  show_states: true
  colorize_states: true
graph_span: 24h
span:
  start: day
now:
  show: true
  label: Now
yaxis:
  - id: price
    decimals: 2
    min: 0
    max: 0.6
series:
  - entity: sensor.frank_energie_prices_current_electricity_price_all_in
    name: Price
    type: column
    yaxis_id: price
    float_precision: 3
    unit: €/kWh
    data_generator: >
      const cheap = 0.25;

      const expensive = 0.40;

      const prices = entity.attributes.prices;

      if (!prices || prices.length === 0) {
        return [{ x: Date.now(), y: 0 }];
      }

      return prices.map((p) => {
        const x = new Date(p.from).getTime() + 30 * 60 * 1000;
        const color = p.price > expensive ? '#F44336' : (p.price <= cheap ? 'green' : '#FFC107');
        return { x: x, y: p.price, fillColor: color };
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
          return realStart.toLocaleString('nl-NL', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
        }
```

</details>

## Today and tomorrow

**ApexCharts.** Needs: nothing extra. Shows 48 hours; the second half fills in when tomorrow's prices are published.

<details>
<summary>Show YAML</summary>

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Electricity prices today and tomorrow
graph_span: 48h
span:
  start: day
now:
  show: true
  label: Now
yaxis:
  - id: price
    decimals: 2
    min: 0
    max: 0.6
series:
  - entity: sensor.frank_energie_prices_current_electricity_price_all_in
    name: Price
    type: column
    yaxis_id: price
    float_precision: 3
    unit: €/kWh
    data_generator: >
      const cheap = 0.25;

      const expensive = 0.40;

      const prices = entity.attributes.prices;

      if (!prices || prices.length === 0) {
        return [{ x: Date.now(), y: 0 }];
      }

      return prices.map((p) => {
        const x = new Date(p.from).getTime() + 30 * 60 * 1000;
        const color = p.price > expensive ? '#F44336' : (p.price <= cheap ? 'green' : '#FFC107');
        return { x: x, y: p.price, fillColor: color };
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
          return realStart.toLocaleString('nl-NL', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
        }
```

</details>

## The next 12 hours

**ApexCharts.** Needs: nothing extra. A compact chart that always starts at the current hour.

<details>
<summary>Show YAML</summary>

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Next 12 hours
graph_span: 12h
span:
  start: hour
yaxis:
  - id: price
    decimals: 2
    min: 0
    max: 0.6
series:
  - entity: sensor.frank_energie_prices_current_electricity_price_all_in
    name: Price
    type: column
    yaxis_id: price
    float_precision: 3
    unit: €/kWh
    data_generator: >
      const cheap = 0.25;

      const expensive = 0.40;

      const prices = (entity.attributes.prices || []).filter((p) => new
      Date(p.till).getTime() > Date.now());

      if (prices.length === 0) {
        return [{ x: Date.now(), y: 0 }];
      }

      return prices.map((p) => {
        const x = new Date(p.from).getTime() + 30 * 60 * 1000;
        const color = p.price > expensive ? '#F44336' : (p.price <= cheap ? 'green' : '#FFC107');
        return { x: x, y: p.price, fillColor: color };
      });
apex_config:
  chart:
    height: 180
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
          return realStart.toLocaleString('nl-NL', { hour: '2-digit', minute: '2-digit' });
        }
```

</details>

## Gas price, today and tomorrow

**ApexCharts.** Needs: nothing extra. The gas price changes once a day, so a stepped line fits best.

<details>
<summary>Show YAML</summary>

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Gas price
  show_states: true
graph_span: 48h
span:
  start: day
now:
  show: true
  label: Now
yaxis:
  - id: price
    decimals: 2
series:
  - entity: sensor.frank_energie_prices_current_gas_price_all_in
    name: Gas
    type: line
    curve: stepline
    yaxis_id: price
    float_precision: 3
    unit: €/m³
    stroke_width: 3
    data_generator: >
      const prices = entity.attributes.prices;

      if (!prices || prices.length === 0) {
        return [[Date.now(), 0]];
      }

      return prices.map((p) => {
        return [new Date(p.from).getTime(), p.price];
      });
apex_config:
  chart:
    height: 180
  xaxis:
    labels:
      datetimeUTC: false
```

</details>

## Current price gauge

**Built-in.** Needs: nothing extra. Set the two `severity` prices to your own cheap and expensive price.

```yaml
type: gauge
entity: sensor.frank_energie_prices_current_electricity_price_all_in
name: Electricity now
min: 0
max: 0.6
needle: true
severity:
  green: 0
  yellow: 0.25
  red: 0.4
```

## Price overview

**Built-in.** Needs: *Daily statistics* and *Upcoming and tomorrow prices*. Remove the rows of a group you don't use.

```yaml
type: entities
title: Electricity prices
entities:
  - entity: sensor.frank_energie_prices_current_electricity_price_all_in
    name: Now
  - entity: sensor.frank_energie_prices_next_electricity_price_all_in
    name: Next
  - entity: sensor.frank_energie_prices_lowest_energy_price_today
    name: Lowest today
  - type: attribute
    entity: sensor.frank_energie_prices_lowest_energy_price_today
    attribute: from_time
    name: Lowest at
    format: time
  - entity: sensor.frank_energie_prices_highest_energy_price_today
    name: Highest today
  - type: attribute
    entity: sensor.frank_energie_prices_highest_energy_price_today
    attribute: from_time
    name: Highest at
    format: time
  - entity: sensor.frank_energie_prices_average_electricity_price_today
    name: Average today
  - entity: sensor.frank_energie_prices_average_electricity_price_tomorrow
    name: Average tomorrow
  - entity: binary_sensor.frank_energie_prices_tomorrow_s_prices_available
    name: Tomorrow's prices
```

## Upcoming prices as a table

**Built-in.** Needs: nothing extra. Lists the next 12 slots; change `[:12]` for more or fewer.

```yaml
type: markdown
title: Upcoming prices
content: |
  | Time | Price |
  |:--|--:|
  {% for p in (state_attr('sensor.frank_energie_prices_current_electricity_price_all_in', 'prices') | selectattr('till', 'gt', now()) | list)[:12] -%}
  | {{ (p['from'] | as_local).strftime('%H:%M') }} | € {{ '%.3f' | format(p.price) }} |
  {% endfor %}
```

## Price history

**Built-in.** Needs: nothing extra. The average, lowest and highest all-in price per day over the last 30 days, from Home Assistant's long-term statistics.

```yaml
type: statistics-graph
title: Electricity price per day
entities:
  - entity: sensor.frank_energie_prices_current_electricity_price_all_in
    name: All-in price
period: day
days_to_show: 30
chart_type: line
stat_types:
  - mean
  - min
  - max
```

---

# Price analysis

These cards need the **Price analysis** group. Colours: yellowgreen = cheap + solar, green = cheap, yellow = normal, red = expensive.

## Analysis today

**ApexCharts.** Columns coloured by [level](Price-analysis#1-price-levels), the solar forecast on the right axis, and an optional *Sell* line: the price minus a fixed amount (here €0.11085) to show what feed-in earns. Remove the *Sell* or *Solar forecast* series if you don't use them.

![Today's prices coloured by level, with the Sell line and the solar forecast](https://raw.githubusercontent.com/archofthings/home-assistant-frank-energie/main/images/prices_today.png)

<details>
<summary>Show YAML</summary>

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

## Analysis tomorrow

**ApexCharts.** The same for tomorrow. Empty until tomorrow's prices are published.

![Tomorrow's prices coloured by level, with the solar forecast](https://raw.githubusercontent.com/archofthings/home-assistant-frank-energie/main/images/prices_tomorrow.png)

<details>
<summary>Show YAML</summary>

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

## Analysis today and tomorrow in one chart

**ApexCharts.** One 48-hour chart with the levels of both days. The card reads the *tomorrow* sensor through `hass.states`.

<details>
<summary>Show YAML</summary>

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Energy prices today and tomorrow
graph_span: 48h
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
series:
  - entity: sensor.frank_energie_prices_electricity_price_analysis_today
    name: Price
    type: column
    yaxis_id: price
    float_precision: 3
    data_generator: >
      const tomorrow =
      hass.states['sensor.frank_energie_prices_electricity_price_analysis_tomorrow'];

      const slots = (entity.attributes.slots || []).concat((tomorrow &&
      tomorrow.attributes.slots) || []);

      if (slots.length === 0) {
        return [{ x: Date.now(), y: 0 }];
      }

      const colorMap = { cheap_solar: 'yellowgreen', cheap: 'green', normal:
      '#FFC107', expensive: '#F44336' };

      return slots.map((p) => {
        const centeredX = new Date(p.from).getTime() + 30 * 60 * 1000;
        return { x: centeredX, y: p.price, fillColor: colorMap[p.level] };
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
          return realStart.toLocaleString('nl-NL', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
        }
```

</details>

## Cheapest period card

**Built-in.** The level now, the two on/off signals and when the next cheapest period starts and ends.

```yaml
type: entities
title: Price analysis
entities:
  - entity: sensor.frank_energie_prices_electricity_price_level
    name: Price level
  - entity: binary_sensor.frank_energie_prices_cheap_electricity_price_now
    name: Cheap now
  - entity: binary_sensor.frank_energie_prices_cheapest_electricity_period_now
    name: Cheapest period now
  - entity: sensor.frank_energie_prices_next_cheapest_electricity_period
    name: Next cheapest period starts
    format: relative
  - type: attribute
    entity: sensor.frank_energie_prices_next_cheapest_electricity_period
    attribute: end
    name: Ends at
    format: time
  - type: attribute
    entity: sensor.frank_energie_prices_next_cheapest_electricity_period
    attribute: average_price
    name: Average price
    suffix: €/kWh
```

---

# Usage and costs

These cards need a login 🔑.

- Cards with **statistics** need the [Energy dashboard statistics](Energy-dashboard-statistics) group. Replace `YOUR_SITE` in the statistic IDs with your own; find them under **Developer tools → Statistics** by searching for `frank_energie:`. You can also build these cards in the visual editor and pick the statistics from the list.
- Frank Energie's data arrives a day later, so the newest column is yesterday.

## Yesterday per hour

**ApexCharts.** Needs: *Daily usage and costs*. Usage and feed-in per hour as columns, costs as a line.

<details>
<summary>Show YAML</summary>

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Yesterday per hour
  show_states: true
graph_span: 24h
span:
  start: day
  offset: -1d
yaxis:
  - id: energy
    decimals: 1
    min: 0
  - id: costs
    opposite: true
    decimals: 2
series:
  - entity: sensor.frank_energie_costs_electricity_usage_yesterday
    name: Usage
    type: column
    yaxis_id: energy
    color: '#2196F3'
    float_precision: 2
    data_generator: >
      const hours = entity.attributes.hours;

      if (!hours || hours.length === 0) {
        return [[Date.now(), 0]];
      }

      return hours.map((h) => {
        return [new Date(h.from).getTime() + 30 * 60 * 1000, h.usage];
      });
  - entity: sensor.frank_energie_costs_feed_in_yesterday
    name: Feed-in
    type: column
    yaxis_id: energy
    color: '#FF9800'
    float_precision: 2
    data_generator: >
      const hours = entity.attributes.hours;

      if (!hours || hours.length === 0) {
        return [[Date.now(), 0]];
      }

      return hours.map((h) => {
        return [new Date(h.from).getTime() + 30 * 60 * 1000, h.usage];
      });
  - entity: sensor.frank_energie_costs_electricity_costs_yesterday
    name: Costs
    type: line
    yaxis_id: costs
    color: '#F44336'
    stroke_width: 3
    float_precision: 2
    data_generator: >
      const hours = entity.attributes.hours;

      if (!hours || hours.length === 0) {
        return [[Date.now(), 0]];
      }

      return hours.map((h) => {
        return [new Date(h.from).getTime() + 30 * 60 * 1000, h.costs];
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
```

</details>

No feed-in? Remove the *Feed-in* series. For gas, use `sensor.frank_energie_costs_gas_usage_yesterday` and `sensor.frank_energie_costs_gas_costs_yesterday` in the same way.

## Costs per day

**Built-in, statistics.** Electricity costs, gas costs and feed-in revenue per day over the last 30 days.

```yaml
type: statistics-graph
title: Costs per day
entities:
  - entity: frank_energie:electricity_costs_YOUR_SITE
    name: Electricity
  - entity: frank_energie:gas_costs_YOUR_SITE
    name: Gas
  - entity: frank_energie:feed_in_revenue_YOUR_SITE
    name: Feed-in revenue
period: day
days_to_show: 30
chart_type: bar
stat_types:
  - change
```

## Usage and feed-in per day

**Built-in, statistics.** Electricity taken from the grid and fed back, per day.

```yaml
type: statistics-graph
title: Electricity per day
entities:
  - entity: frank_energie:electricity_usage_YOUR_SITE
    name: Usage
  - entity: frank_energie:feed_in_YOUR_SITE
    name: Feed-in
period: day
days_to_show: 30
chart_type: bar
stat_types:
  - change
```

Gas per day (a separate card, because the unit differs):

```yaml
type: statistics-graph
title: Gas per day
entities:
  - entity: frank_energie:gas_usage_YOUR_SITE
    name: Gas
period: day
days_to_show: 30
chart_type: bar
stat_types:
  - change
```

## Costs per month

**Built-in, statistics.** The last 12 months. The history starts 30 days before you turned the statistics on and grows from there.

```yaml
type: statistics-graph
title: Costs per month
entities:
  - entity: frank_energie:electricity_costs_YOUR_SITE
    name: Electricity
  - entity: frank_energie:gas_costs_YOUR_SITE
    name: Gas
  - entity: frank_energie:feed_in_revenue_YOUR_SITE
    name: Feed-in revenue
period: month
days_to_show: 365
chart_type: bar
stat_types:
  - change
```

## Usage per month

**Built-in, statistics.**

```yaml
type: statistics-graph
title: Electricity per month
entities:
  - entity: frank_energie:electricity_usage_YOUR_SITE
    name: Usage
  - entity: frank_energie:feed_in_YOUR_SITE
    name: Feed-in
period: month
days_to_show: 365
chart_type: bar
stat_types:
  - change
```

## Invoices per month, this year and last year

**ApexCharts.** Needs: *Costs and invoices*. Every invoice of this year next to the same month of last year, from the `invoices` attribute. This works right away, also for the months before you installed the integration.

<details>
<summary>Show YAML</summary>

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Invoices per month
  show_states: true
graph_span: 1y
span:
  start: year
yaxis:
  - id: amount
    decimals: 0
    min: 0
series:
  - entity: sensor.frank_energie_costs_total_last_year
    name: Last year
    type: column
    yaxis_id: amount
    color: '#9E9E9E'
    float_precision: 2
    unit: €
    data_generator: >
      const invoices = entity.attributes.invoices;

      if (!invoices || invoices.length === 0) {
        return [[Date.now(), 0]];
      }

      return invoices.map((i) => {
        const d = new Date(i.start_date + 'T12:00:00');
        d.setFullYear(d.getFullYear() + 1);
        d.setDate(15);
        return [d.getTime(), i.total_amount];
      });
  - entity: sensor.frank_energie_costs_total_this_year
    name: This year
    type: column
    yaxis_id: amount
    color: '#2196F3'
    float_precision: 2
    unit: €
    data_generator: >
      const invoices = entity.attributes.invoices;

      if (!invoices || invoices.length === 0) {
        return [[Date.now(), 0]];
      }

      return invoices.map((i) => {
        const d = new Date(i.start_date + 'T12:00:00');
        d.setDate(15);
        return [d.getTime(), i.total_amount];
      });
apex_config:
  chart:
    height: 240
  xaxis:
    labels:
      datetimeUTC: false
      format: MMM
  tooltip:
    x:
      format: MMMM
```

</details>

The header shows the totals of both years. Last year's invoices are moved one year forward so the same months stand next to each other.

## This month: actual and expected

**Built-in.** Needs: *Costs and invoices*, and *Monthly usage and costs* for the usage rows.

```yaml
type: entities
title: This month
entities:
  - entity: sensor.frank_energie_costs_actual_monthly_cost
    name: Costs so far
  - entity: sensor.frank_energie_costs_expected_monthly_cost_until_now
    name: Expected so far
  - entity: sensor.frank_energie_costs_expected_cost_this_month
    name: Expected whole month
  - entity: sensor.frank_energie_costs_electricity_usage_this_month
    name: Electricity
  - type: attribute
    entity: sensor.frank_energie_costs_electricity_costs_this_month
    attribute: average_price
    name: Average electricity price
    suffix: €/kWh
  - entity: sensor.frank_energie_costs_gas_usage_this_month
    name: Gas
  - entity: sensor.frank_energie_costs_feed_in_this_month
    name: Feed-in
  - entity: sensor.frank_energie_costs_fixed_costs_this_month_expected
    name: Fixed costs (expected)
```

A gauge that shows whether you are above or below the expected costs:

```yaml
type: gauge
entity: sensor.frank_energie_costs_actual_monthly_cost
name: Costs this month
min: 0
max: 200
needle: true
```

Set `max` to roughly your expected costs for a whole month.

## This month at a glance

**Mushroom.** Needs: *Costs and invoices*. Three tiles like the overview in the Frank Energie app: the expected costs up to the last meter reading, the real costs, and the difference.

![Expected, real and saved costs of this month as three tiles](https://raw.githubusercontent.com/archofthings/home-assistant-frank-energie/main/images/costs_this_month.png)

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
    primary: Cost
    secondary: '€ {{ "%.2f" | format(states("sensor.frank_energie_costs_actual_monthly_cost") | float(0)) | replace(".", ",") }}'
    icon: mdi:cash
    color: red
    tap_action:
      action: none
  - type: custom:mushroom-template-card
    primary: Saved
    secondary: '€ {{ "%.2f" | format(states("sensor.frank_energie_costs_actual_monthly_cost") | float(0) - states("sensor.frank_energie_costs_expected_monthly_cost_until_now") | float(0)) | replace(".", ",") }}'
    icon: mdi:cash-check
    color: green
    tap_action:
      action: none
```

*Saved* is real minus expected, like *Verschil* in the app: a negative amount means you are below the expected costs. The amounts use a decimal comma; remove `| replace(".", ",")` for a decimal point.

## Cost breakdown this month

**Mushroom.** Needs: *Costs and invoices* and *Monthly usage and costs*. Usage and costs of gas, electricity and feed-in this month, plus the fixed costs so far.

![Usage and costs of gas, electricity and feed-in, and the fixed costs, as four tiles](https://raw.githubusercontent.com/archofthings/home-assistant-frank-energie/main/images/costs_breakdown.png)

<details>
<summary>Show YAML</summary>

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

There is no sensor for the fixed costs so far, so the *Fixed* tile calculates them: the real costs minus gas and electricity, plus the feed-in revenue. No gas or no feed-in? Remove that tile and its part of the *Fixed* calculation, and lower `columns`.

## Month chart with navigation

**ApexCharts, Mushroom, statistics.** Costs or usage per day as stacked columns, for the current month or an earlier one, like the *Inzicht* page of the Frank Energie app. Two rows of buttons choose the month and switch between costs, gas and electricity.

![Costs per day of one month as stacked columns, with month buttons above and chart buttons below](https://raw.githubusercontent.com/archofthings/home-assistant-frank-energie/main/images/costs_month_chart.png)

The buttons need two helpers. Create them under **Settings → Devices & services → Helpers**:

| Helper | Type | Settings |
|---|---|---|
| `input_number.frank_costs_month_offset` | Number | Minimum `-24`, maximum `0`, step `1`. Set its value to `0` after creating it |
| `input_select.frank_costs_chart` | Dropdown | Options `Costs`, `Gas`, `Electricity` |

`0` is the current month, `-1` the previous one. Then add the cards below in this order. They are separate cards, so the charts can be shown and hidden.

**1. Month buttons.** The middle button shows the chosen month and jumps back to the current month.

<details>
<summary>Show YAML</summary>

```yaml
type: grid
columns: 3
square: false
cards:
  - type: custom:mushroom-template-card
    primary: Previous
    icon: mdi:chevron-left
    color: blue
    tap_action:
      action: perform-action
      perform_action: input_number.decrement
      target:
        entity_id: input_number.frank_costs_month_offset
  - type: custom:mushroom-template-card
    primary: >-
      {% set off = states("input_number.frank_costs_month_offset") | int(0) %}{% set m = now().month - 1 + off %}{{ now().replace(day=1).replace(year=now().year + m // 12, month=m % 12 + 1).strftime("%B %Y") }}
    icon: mdi:calendar-month
    color: grey
    tap_action:
      action: perform-action
      perform_action: input_number.set_value
      target:
        entity_id: input_number.frank_costs_month_offset
      data:
        value: 0
  - type: custom:mushroom-template-card
    primary: Next
    icon: mdi:chevron-right
    color: >-
      {% if states("input_number.frank_costs_month_offset") | int(0) < 0 %}blue{% else %}grey{% endif %}
    tap_action:
      action: perform-action
      perform_action: input_number.increment
      target:
        entity_id: input_number.frank_costs_month_offset
```

</details>

**2. The three charts.** Only the chart that matches the chosen option is visible. Replace `YOUR_SITE` in every `const id` line.

<details>
<summary>Show YAML: costs</summary>

```yaml
type: custom:apexcharts-card
header:
  show: false
graph_span: 31d
span:
  start: month
stacked: true
update_delay: 200ms
series:
  - entity: input_number.frank_costs_month_offset
    name: Gas
    type: column
    color: '#5BB4D6'
    unit: €
    float_precision: 2
    show:
      legend_value: false
    data_generator: |
      const id = "frank_energie:gas_costs_YOUR_SITE";
      const sign = 1;
      const off = parseInt(entity.state) || 0;
      const y = start.getFullYear();
      const m = start.getMonth();
      const from = new Date(y, m + off, 1);
      const to = new Date(y, m + off + 1, 1);
      const r = await hass.callWS({type: "recorder/statistics_during_period", start_time: from.toISOString(), end_time: to.toISOString(), statistic_ids: [id], period: "day", types: ["change"]});
      const byDay = {};
      (r[id] || []).forEach((s) => { byDay[new Date(s.start).getDate()] = sign * s.change; });
      const days = new Date(y, m + off + 1, 0).getDate();
      const out = [];
      for (let k = 1; k <= days; k++) { out.push([new Date(y, m, k).getTime(), byDay[k] || 0]); }
      return out;
  - entity: input_number.frank_costs_month_offset
    name: Electricity
    type: column
    color: '#F2C043'
    unit: €
    float_precision: 2
    show:
      legend_value: false
    data_generator: |
      const id = "frank_energie:electricity_costs_YOUR_SITE";
      const sign = 1;
      const off = parseInt(entity.state) || 0;
      const y = start.getFullYear();
      const m = start.getMonth();
      const from = new Date(y, m + off, 1);
      const to = new Date(y, m + off + 1, 1);
      const r = await hass.callWS({type: "recorder/statistics_during_period", start_time: from.toISOString(), end_time: to.toISOString(), statistic_ids: [id], period: "day", types: ["change"]});
      const byDay = {};
      (r[id] || []).forEach((s) => { byDay[new Date(s.start).getDate()] = sign * s.change; });
      const days = new Date(y, m + off + 1, 0).getDate();
      const out = [];
      for (let k = 1; k <= days; k++) { out.push([new Date(y, m, k).getTime(), byDay[k] || 0]); }
      return out;
  - entity: input_number.frank_costs_month_offset
    name: Feed-in
    type: column
    color: '#E8894F'
    unit: €
    float_precision: 2
    show:
      legend_value: false
    data_generator: |
      const id = "frank_energie:feed_in_revenue_YOUR_SITE";
      const sign = -1;
      const off = parseInt(entity.state) || 0;
      const y = start.getFullYear();
      const m = start.getMonth();
      const from = new Date(y, m + off, 1);
      const to = new Date(y, m + off + 1, 1);
      const r = await hass.callWS({type: "recorder/statistics_during_period", start_time: from.toISOString(), end_time: to.toISOString(), statistic_ids: [id], period: "day", types: ["change"]});
      const byDay = {};
      (r[id] || []).forEach((s) => { byDay[new Date(s.start).getDate()] = sign * s.change; });
      const days = new Date(y, m + off + 1, 0).getDate();
      const out = [];
      for (let k = 1; k <= days; k++) { out.push([new Date(y, m, k).getTime(), byDay[k] || 0]); }
      return out;
apex_config:
  chart:
    height: 260
    stacked: true
  xaxis:
    labels:
      datetimeUTC: false
      format: dd
  yaxis:
    decimalsInFloat: 2
  plotOptions:
    bar:
      columnWidth: 80%
  tooltip:
    x:
      formatter: |
        EVAL:function(val) { return "Day " + new Date(val).getDate(); }
visibility:
  - condition: state
    entity: input_select.frank_costs_chart
    state: Costs
```

</details>

<details>
<summary>Show YAML: gas</summary>

```yaml
type: custom:apexcharts-card
header:
  show: false
graph_span: 31d
span:
  start: month
stacked: true
update_delay: 200ms
series:
  - entity: input_number.frank_costs_month_offset
    name: Gas
    type: column
    color: '#5BB4D6'
    unit: m³
    float_precision: 2
    show:
      legend_value: false
    data_generator: |
      const id = "frank_energie:gas_usage_YOUR_SITE";
      const sign = 1;
      const off = parseInt(entity.state) || 0;
      const y = start.getFullYear();
      const m = start.getMonth();
      const from = new Date(y, m + off, 1);
      const to = new Date(y, m + off + 1, 1);
      const r = await hass.callWS({type: "recorder/statistics_during_period", start_time: from.toISOString(), end_time: to.toISOString(), statistic_ids: [id], period: "day", types: ["change"]});
      const byDay = {};
      (r[id] || []).forEach((s) => { byDay[new Date(s.start).getDate()] = sign * s.change; });
      const days = new Date(y, m + off + 1, 0).getDate();
      const out = [];
      for (let k = 1; k <= days; k++) { out.push([new Date(y, m, k).getTime(), byDay[k] || 0]); }
      return out;
apex_config:
  chart:
    height: 260
    stacked: true
  xaxis:
    labels:
      datetimeUTC: false
      format: dd
  yaxis:
    decimalsInFloat: 2
  plotOptions:
    bar:
      columnWidth: 80%
  tooltip:
    x:
      formatter: |
        EVAL:function(val) { return "Day " + new Date(val).getDate(); }
visibility:
  - condition: state
    entity: input_select.frank_costs_chart
    state: Gas
```

</details>

<details>
<summary>Show YAML: electricity and feed-in</summary>

```yaml
type: custom:apexcharts-card
header:
  show: false
graph_span: 31d
span:
  start: month
stacked: true
update_delay: 200ms
series:
  - entity: input_number.frank_costs_month_offset
    name: Electricity
    type: column
    color: '#F2C043'
    unit: kWh
    float_precision: 2
    show:
      legend_value: false
    data_generator: |
      const id = "frank_energie:electricity_usage_YOUR_SITE";
      const sign = 1;
      const off = parseInt(entity.state) || 0;
      const y = start.getFullYear();
      const m = start.getMonth();
      const from = new Date(y, m + off, 1);
      const to = new Date(y, m + off + 1, 1);
      const r = await hass.callWS({type: "recorder/statistics_during_period", start_time: from.toISOString(), end_time: to.toISOString(), statistic_ids: [id], period: "day", types: ["change"]});
      const byDay = {};
      (r[id] || []).forEach((s) => { byDay[new Date(s.start).getDate()] = sign * s.change; });
      const days = new Date(y, m + off + 1, 0).getDate();
      const out = [];
      for (let k = 1; k <= days; k++) { out.push([new Date(y, m, k).getTime(), byDay[k] || 0]); }
      return out;
  - entity: input_number.frank_costs_month_offset
    name: Feed-in
    type: column
    color: '#E8894F'
    unit: kWh
    float_precision: 2
    show:
      legend_value: false
    data_generator: |
      const id = "frank_energie:feed_in_YOUR_SITE";
      const sign = -1;
      const off = parseInt(entity.state) || 0;
      const y = start.getFullYear();
      const m = start.getMonth();
      const from = new Date(y, m + off, 1);
      const to = new Date(y, m + off + 1, 1);
      const r = await hass.callWS({type: "recorder/statistics_during_period", start_time: from.toISOString(), end_time: to.toISOString(), statistic_ids: [id], period: "day", types: ["change"]});
      const byDay = {};
      (r[id] || []).forEach((s) => { byDay[new Date(s.start).getDate()] = sign * s.change; });
      const days = new Date(y, m + off + 1, 0).getDate();
      const out = [];
      for (let k = 1; k <= days; k++) { out.push([new Date(y, m, k).getTime(), byDay[k] || 0]); }
      return out;
apex_config:
  chart:
    height: 260
    stacked: true
  xaxis:
    labels:
      datetimeUTC: false
      format: dd
  yaxis:
    decimalsInFloat: 2
  plotOptions:
    bar:
      columnWidth: 80%
  tooltip:
    x:
      formatter: |
        EVAL:function(val) { return "Day " + new Date(val).getDate(); }
visibility:
  - condition: state
    entity: input_select.frank_costs_chart
    state: Electricity
```

</details>

**3. Chart buttons.** The active one is green.

<details>
<summary>Show YAML</summary>

```yaml
type: grid
columns: 3
square: false
cards:
  - type: custom:mushroom-template-card
    primary: Costs
    icon: mdi:currency-eur
    color: >-
      {% if is_state("input_select.frank_costs_chart", "Costs") %}green{% else %}grey{% endif %}
    tap_action:
      action: perform-action
      perform_action: input_select.select_option
      target:
        entity_id: input_select.frank_costs_chart
      data:
        option: Costs
  - type: custom:mushroom-template-card
    primary: Gas
    icon: mdi:fire
    color: >-
      {% if is_state("input_select.frank_costs_chart", "Gas") %}green{% else %}grey{% endif %}
    tap_action:
      action: perform-action
      perform_action: input_select.select_option
      target:
        entity_id: input_select.frank_costs_chart
      data:
        option: Gas
  - type: custom:mushroom-template-card
    primary: Electricity
    icon: mdi:lightning-bolt
    color: >-
      {% if is_state("input_select.frank_costs_chart", "Electricity") %}green{% else %}grey{% endif %}
    tap_action:
      action: perform-action
      perform_action: input_select.select_option
      target:
        entity_id: input_select.frank_costs_chart
      data:
        option: Electricity
```

</details>

Good to know:

- The x-axis shows day numbers. An earlier month is drawn on the days of the current month, so when the current month is shorter, the last days of the earlier month are not shown.
- The history starts 30 days before you turned the statistics on; earlier months stay empty.
- The option names appear in the dropdown helper, in the `visibility` of each chart and in the buttons. Keep them the same when you rename them.
- The charts load their data when the page opens and when you press a button. Reload the page to see new days.

## Real and saved costs per month

**ApexCharts.** Needs: *Costs and invoices*. One stacked column per month of this year: the real costs, and on top what you saved compared to the expected costs. The whole column is the expected amount; when a month costs more than expected, the saved part goes below zero.

![Real and saved costs per month as stacked columns](https://raw.githubusercontent.com/archofthings/home-assistant-frank-energie/main/images/costs_real_vs_saved.png)

<details>
<summary>Show YAML</summary>

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Real vs saved costs per month
graph_span: 1y
span:
  start: year
stacked: true
update_interval: 1h
series:
  - entity: sensor.frank_energie_costs_actual_monthly_cost
    name: Real
    type: column
    color: red
    unit: €
    float_precision: 2
    show:
      legend_value: false
    data_generator: |
      const a = "sensor.frank_energie_costs_actual_monthly_cost";
      const e = "sensor.frank_energie_costs_expected_monthly_cost_until_now";
      const y = start.getFullYear();
      const r = await hass.callWS({type: "recorder/statistics_during_period", start_time: new Date(y, 0, 1).toISOString(), end_time: new Date(y + 1, 0, 1).toISOString(), statistic_ids: [a, e], period: "month", types: ["state"]});
      const act = {};
      const exp = {};
      (r[a] || []).forEach((s) => { act[new Date(s.start).getMonth()] = s.state; });
      (r[e] || []).forEach((s) => { exp[new Date(s.start).getMonth()] = s.state; });
      const out = [];
      for (let m = 0; m < 12; m++) { const real = act[m] || 0; const saved = (exp[m] || 0) - real; out.push([new Date(y, m, 1).getTime(), real]); }
      return out;
  - entity: sensor.frank_energie_costs_actual_monthly_cost
    name: Saved
    type: column
    color: green
    unit: €
    float_precision: 2
    show:
      legend_value: false
    data_generator: |
      const a = "sensor.frank_energie_costs_actual_monthly_cost";
      const e = "sensor.frank_energie_costs_expected_monthly_cost_until_now";
      const y = start.getFullYear();
      const r = await hass.callWS({type: "recorder/statistics_during_period", start_time: new Date(y, 0, 1).toISOString(), end_time: new Date(y + 1, 0, 1).toISOString(), statistic_ids: [a, e], period: "month", types: ["state"]});
      const act = {};
      const exp = {};
      (r[a] || []).forEach((s) => { act[new Date(s.start).getMonth()] = s.state; });
      (r[e] || []).forEach((s) => { exp[new Date(s.start).getMonth()] = s.state; });
      const out = [];
      for (let m = 0; m < 12; m++) { const real = act[m] || 0; const saved = (exp[m] || 0) - real; out.push([new Date(y, m, 1).getTime(), saved]); }
      return out;
apex_config:
  chart:
    height: 260
    stacked: true
  xaxis:
    labels:
      datetimeUTC: false
      format: MMM
  yaxis:
    decimalsInFloat: 0
  plotOptions:
    bar:
      columnWidth: 70%
  tooltip:
    x:
      formatter: |
        EVAL:function(val) { return new Date(val).toLocaleString("en-GB", { month: "long", year: "numeric" }); }
```

</details>

The chart reads the history that Home Assistant keeps of the two monthly sensors, so it starts in the month you installed the integration and grows from there. A finished month shows the last value of that month, which can miss its final day because Frank Energie's data arrives a day later. These are total costs including the fixed costs.

## Something missing?

Made a nice chart with this integration? Share it in a [GitHub issue](https://github.com/archofthings/home-assistant-frank-energie/issues) and it can be added here.
