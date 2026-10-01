# Price list and get_prices action

Two ways to get **all** known prices of today and tomorrow:

| | `prices` attribute | `frank_energie.get_prices` action |
|---|---|---|
| Where | On the current all-in, market and including-tax sensors | An action you call from a script or automation |
| Contains | `from`, `till`, `price` | `start`, `end` and all six price components |
| Electricity and gas | One sensor each | Both in one response |
| Limit the period | With template filters | With `start` and `end` |
| Best for | Templates and charts | Scripts, automations, Node-RED |

Neither of them contacts Frank Energie: both read the prices Home Assistant already has.

## The `prices` attribute

On these sensors (see [Sensors](Sensors#current-prices)):

| Sensor | `price` is |
|---|---|
| Current electricity price (All-in) | All-in price |
| Current electricity market price | Market price |
| Current electricity price including tax | Market price + VAT |
| Current gas price (All-in), market price, including tax | The same for gas |

Every entry has `from`, `till` and `price` (3 decimals). With quarter-hour prices the list has up to 200 entries, so it is **not stored in history**; it is always on the live state.

### Template examples

```jinja
{# Lowest price in the next six hours #}
{{ state_attr('sensor.frank_energie_prices_current_electricity_price_all_in', 'prices')
   | selectattr('from', 'gt', now())
   | selectattr('till', 'lt', now() + timedelta(hours=6))
   | min(attribute='price') }}
```

```jinja
{# Average price between 18:00 and 22:00 today #}
{% set prices = state_attr('sensor.frank_energie_prices_current_electricity_price_all_in', 'prices')
   | selectattr('from', 'ge', today_at('18:00'))
   | selectattr('from', 'lt', today_at('22:00'))
   | map(attribute='price') | list %}
{{ (prices | sum / prices | count) | round(3) if prices else 'unknown' }}
```

```jinja
{# The three cheapest slots still to come #}
{% for p in (state_attr('sensor.frank_energie_prices_current_electricity_price_all_in', 'prices')
   | selectattr('from', 'gt', now()) | sort(attribute='price'))[:3] %}
{{ (p['from'] | as_local).strftime('%H:%M') }}: € {{ p.price }}
{% endfor %}
```

```jinja
{# Number of slots today with a negative market price #}
{{ state_attr('sensor.frank_energie_prices_current_electricity_market_price', 'prices')
   | selectattr('from', 'ge', today_at('00:00'))
   | selectattr('from', 'lt', today_at('00:00') + timedelta(days=1))
   | selectattr('price', 'lt', 0) | list | count }}
```

Looking for "the cheapest block of N hours"? The [price analysis](Price-analysis) calculates that for you.

## The `frank_energie.get_prices` action

Returns the price slots with all components, for electricity and gas.

### Fields

| Field | Required | Meaning |
|---|---|---|
| `config_entry_id` | Yes | Your Frank Energie entry. In **Developer tools → Actions**, choose the action and pick your entry in the form; switch to YAML mode to see its ID. |
| `start` | No | Only slots that **end after** this time. Without it: from the first known slot. |
| `end` | No | Only slots that **start before** this time. Without it: up to the last known slot. |

So a slot that is partly inside the period is included. `start` must be before `end`.

### Response

```yaml
electricity:
  - start: "2026-10-01T13:00:00+02:00"
    end: "2026-10-01T13:15:00+02:00"
    price: 0.2431
    market_price: 0.0812
    market_price_including_tax: 0.09825
    vat: 0.01705
    sourcing_markup: 0.0182
    energy_tax: 0.12665
gas:
  - start: "2026-10-01T06:00:00+02:00"
    end: "2026-10-01T07:00:00+02:00"
    price: 1.2874
    market_price: 0.3412
    market_price_including_tax: 0.41285
    vat: 0.07165
    sourcing_markup: 0.0971
    energy_tax: 0.77745
```

| Key | Meaning |
|---|---|
| `start`, `end` | The slot, in the [time zone you chose](Configuration#time-zone-for-price-times) |
| `price` | All-in price |
| `market_price` | Market price without tax |
| `market_price_including_tax` | Market price + VAT |
| `vat` | VAT |
| `sourcing_markup` | Frank Energie's markup |
| `energy_tax` | Energy tax |

Amounts have 5 decimals. `electricity` is in €/kWh, `gas` in €/m³. A list is empty when there are no prices in the period.

> [!NOTE]
> The action uses `start`/`end`, the `prices` attribute uses `from`/`till`.

### Errors

| Message | Cause |
|---|---|
| *Frank Energie config entry "…" not found.* | The `config_entry_id` is wrong or belongs to another integration. |
| *Frank Energie config entry "…" is not loaded.* | The entry is disabled or failed to start. |
| *The start time must be before the end time.* | `start` is the same as or later than `end`. |

### Examples

Try it in **Developer tools → Actions**:

```yaml
action: frank_energie.get_prices
data:
  config_entry_id: YOUR_ENTRY_ID
```

Cheapest slot in the next six hours, in a notification:

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

Tomorrow's prices only:

```yaml
- action: frank_energie.get_prices
  data:
    config_entry_id: YOUR_ENTRY_ID
    start: "{{ today_at('00:00') + timedelta(days=1) }}"
    end: "{{ today_at('00:00') + timedelta(days=2) }}"
  response_variable: tomorrow
```

A template sensor with the share of tax in the current price:

```yaml
template:
  - triggers:
      - trigger: time_pattern
        minutes: "/15"
    actions:
      - action: frank_energie.get_prices
        data:
          config_entry_id: YOUR_ENTRY_ID
          start: "{{ now() }}"
          end: "{{ now() + timedelta(minutes=1) }}"
        response_variable: frank
    sensor:
      - name: Electricity tax share
        unit_of_measurement: "%"
        state: >
          {% set p = frank.electricity | first %}
          {{ ((p.energy_tax + p.vat) / p.price * 100) | round(0) if p and p.price > 0 else none }}
```

### Node-RED

Use an **Action** node with `frank_energie.get_prices`, the data `{"config_entry_id": "YOUR_ENTRY_ID"}`, and the response in `msg.payload`. Parse the times with `new Date(slot.start)`; then your flow works with both time zone settings.
