# Automation examples

Copy an example into **Settings → Automations & scenes → Create automation → Edit in YAML** and replace the entity IDs with your own. Each example says which [sensor group](Configuration#sensor-groups) it needs.

- [Run an appliance in the cheapest period](#run-an-appliance-in-the-cheapest-period)
- [Run something whenever the price is cheap](#run-something-whenever-the-price-is-cheap)
- [Stop a consumer when the price is expensive](#stop-a-consumer-when-the-price-is-expensive)
- [Use cheap power only when the sun shines](#use-cheap-power-only-when-the-sun-shines)
- [Notify when tomorrow's prices arrive](#notify-when-tomorrows-prices-arrive)
- [Announce the cheapest period every morning](#announce-the-cheapest-period-every-morning)
- [Warn before a negative price](#warn-before-a-negative-price)
- [Finish before a deadline](#finish-before-a-deadline)
- [Warn when the month costs more than expected](#warn-when-the-month-costs-more-than-expected)
- [Daily cost report](#daily-cost-report)

## Run an appliance in the cheapest period

Needs: *Price analysis*. Starts at the beginning of today's cheapest period and stops at the end. Set the period length to the running time of the appliance in the [options](Configuration#cheapest-period-relative).

```yaml
alias: Dishwasher in the cheapest period
triggers:
  - trigger: state
    entity_id: binary_sensor.frank_energie_prices_cheapest_electricity_period_now
    to: "on"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.dishwasher
```

## Run something whenever the price is cheap

Needs: *Price analysis*. Follows the binary sensor: on when cheap, off when not.

```yaml
alias: Charge the home battery when cheap
triggers:
  - trigger: state
    entity_id: binary_sensor.frank_energie_prices_cheap_electricity_price_now
    to:
      - "on"
      - "off"
actions:
  - action: "switch.turn_{{ trigger.to_state.state }}"
    target:
      entity_id: switch.battery_charging
```

## Stop a consumer when the price is expensive

Needs: *Price analysis*.

```yaml
alias: Pause the boiler when expensive
triggers:
  - trigger: state
    entity_id: sensor.frank_energie_prices_electricity_price_level
actions:
  - if:
      - condition: state
        entity_id: sensor.frank_energie_prices_electricity_price_level
        state: expensive
    then:
      - action: switch.turn_off
        target:
          entity_id: switch.boiler
    else:
      - action: switch.turn_on
        target:
          entity_id: switch.boiler
```

## Use cheap power only when the sun shines

Needs: *Price analysis* with a [solar forecast](Price-analysis#solar-forecast).

```yaml
alias: Heat the buffer on cheap solar hours
triggers:
  - trigger: state
    entity_id: sensor.frank_energie_prices_electricity_price_level
    to: cheap_solar
actions:
  - action: climate.set_temperature
    target:
      entity_id: climate.buffer
    data:
      temperature: 60
```

## Notify when tomorrow's prices arrive

Needs: *Upcoming and tomorrow prices*.

```yaml
alias: Tomorrow's prices are in
triggers:
  - trigger: state
    entity_id: binary_sensor.frank_energie_prices_tomorrow_s_prices_available
    from: "off"
    to: "on"
actions:
  - action: notify.notify
    data:
      title: Tomorrow's electricity prices
      message: >
        Average € {{ states('sensor.frank_energie_prices_average_electricity_price_tomorrow') | float | round(3) }},
        lowest € {{ states('sensor.frank_energie_prices_lowest_electricity_price_tomorrow') | float | round(3) }}
        at {{ (state_attr('sensor.frank_energie_prices_lowest_electricity_price_tomorrow', 'from_time') | as_local).strftime('%H:%M') }},
        highest € {{ states('sensor.frank_energie_prices_highest_electricity_price_tomorrow') | float | round(3) }}.
```

## Announce the cheapest period every morning

Needs: *Price analysis*.

```yaml
alias: Morning price briefing
triggers:
  - trigger: time
    at: "07:30:00"
actions:
  - action: notify.notify
    data:
      message: >
        {% set period = state_attr('sensor.frank_energie_prices_electricity_price_analysis_today', 'cheapest_period') %}
        Cheapest today: {{ (period.start | as_datetime | as_local).strftime('%H:%M') }}
        to {{ (period.end | as_datetime | as_local).strftime('%H:%M') }},
        on average € {{ period.average_price | round(3) }} per kWh.
```

## Warn before a negative price

Needs: nothing extra. Checks every hour whether an all-in price below zero is coming in the next three hours.

```yaml
alias: Negative price coming
triggers:
  - trigger: time_pattern
    minutes: 0
conditions:
  - condition: template
    value_template: >
      {{ state_attr('sensor.frank_energie_prices_current_electricity_price_all_in', 'prices')
         | selectattr('from', 'gt', now())
         | selectattr('from', 'lt', now() + timedelta(hours=3))
         | selectattr('price', 'lt', 0) | list | count > 0 }}
actions:
  - action: notify.notify
    data:
      message: The electricity price goes below zero within three hours.
```

## Finish before a deadline

Needs: nothing extra. Finds the cheapest three hours between now and 07:00 tomorrow with the `get_prices` action and starts the car charger at that time. Change `slots_needed` to the number of slots you need: 3 for three hours with hourly prices, 12 with quarter-hour prices.

```yaml
alias: Charge the car before 07:00
triggers:
  - trigger: time
    at: "20:00:00"
actions:
  - action: frank_energie.get_prices
    data:
      config_entry_id: YOUR_ENTRY_ID
      start: "{{ now() }}"
      end: "{{ today_at('07:00') + timedelta(days=1) }}"
    response_variable: frank
  - variables:
      slots_needed: 3
      best_start: >
        {% set slots = frank.electricity %}
        {% set ns = namespace(best=none, start=none) %}
        {% for i in range(0, (slots | count) - slots_needed + 1) %}
          {% set total = slots[i:i + slots_needed] | sum(attribute='price') %}
          {% if ns.best is none or total < ns.best %}
            {% set ns.best = total %}
            {% set ns.start = slots[i].start %}
          {% endif %}
        {% endfor %}
        {{ ns.start }}
  - wait_template: "{{ now() >= best_start | as_datetime }}"
  - action: switch.turn_on
    target:
      entity_id: switch.car_charger
```

For a block without a deadline, the [cheapest period](Price-analysis#2-cheapest-period) does this without a template.

## Warn when the month costs more than expected

Needs: *Costs and invoices* 🔑.

```yaml
alias: Energy costs above expectation
triggers:
  - trigger: template
    value_template: >
      {{ states('sensor.frank_energie_costs_actual_monthly_cost') | float(0)
         > states('sensor.frank_energie_costs_expected_monthly_cost_until_now') | float(0) * 1.1 }}
actions:
  - action: notify.notify
    data:
      message: >
        Energy costs this month are € {{ states('sensor.frank_energie_costs_actual_monthly_cost') }},
        more than 10% above the expected € {{ states('sensor.frank_energie_costs_expected_monthly_cost_until_now') }}.
```

## Daily cost report

Needs: *Daily usage and costs* 🔑. Sent when Frank Energie's numbers for yesterday arrive.

```yaml
alias: Yesterday's energy report
triggers:
  - trigger: state
    entity_id: sensor.frank_energie_costs_electricity_usage_yesterday
    attribute: date
conditions:
  - condition: template
    value_template: "{{ trigger.to_state.attributes.date is defined }}"
actions:
  - action: notify.notify
    data:
      message: >
        {{ state_attr('sensor.frank_energie_costs_electricity_usage_yesterday', 'date') }}:
        {{ states('sensor.frank_energie_costs_electricity_usage_yesterday') | float | round(1) }} kWh
        for € {{ states('sensor.frank_energie_costs_electricity_costs_yesterday') | float | round(2) }}.
```

## Tips

- Add a condition on the appliance itself (door closed, car connected) so a price signal alone never starts something that is not ready.
- Give automations that follow a binary sensor a fallback, for example a latest start time, for days on which the sensor stays off (*Only when cheap*) or prices are unavailable.
- In templates, compare times with `now()` and parse them with `as_datetime`; then the [time zone option](Configuration#time-zone-for-price-times) does not matter.
