# Energy dashboard statistics

Imports Frank Energie's **hourly usage and costs** as long-term statistics, so the Energy dashboard can show exactly what Frank Energie measured and billed. 🔑 Needs a login.

## Turn it on

**Configure** on the integration → tick **Energy dashboard statistics (hourly usage and costs)** → **Submit**.

This creates **no entities**. Six statistics appear in the pickers of the Energy dashboard and of statistics cards:

| Statistic | Name in the picker | Unit | ID |
|---|---|---|---|
| Electricity usage | *address* Electricity usage | kWh | `frank_energie:electricity_usage_<site>` |
| Electricity costs | *address* Electricity costs | € | `frank_energie:electricity_costs_<site>` |
| Feed-in | *address* Feed-in | kWh | `frank_energie:feed_in_<site>` |
| Feed-in revenue | *address* Feed-in revenue | € | `frank_energie:feed_in_revenue_<site>` |
| Gas usage | *address* Gas usage | m³ | `frank_energie:gas_usage_<site>` |
| Gas costs | *address* Gas costs | € | `frank_energie:gas_costs_<site>` |

*address* is the name of your integration entry (street and house number). `<site>` is a code for your delivery address. Find your exact IDs under **Developer tools → Statistics** by searching for `frank_energie:`.

Gas and feed-in statistics only appear when your account has gas or feed-in.

## Use it in the Energy dashboard

**Settings → Dashboards → Energy:**

| Section | Choose | Costs |
|---|---|---|
| **Grid consumption** | *address* Electricity usage | **Use an entity tracking the total costs** → *address* Electricity costs |
| **Return to grid** | *address* Feed-in | **Use an entity tracking the total money received** → *address* Feed-in revenue |
| **Gas consumption** | *address* Gas usage | **Use an entity tracking the total costs** → *address* Gas costs |

> [!NOTE]
> Frank Energie's data arrives **a day later**. With these statistics, today stays empty in the Energy dashboard until tomorrow. If you want to see today live, keep your own meter (for example a P1 reader) for consumption and use only Frank Energie's **costs**, or keep your own meter in the dashboard and use the Frank statistics in separate [charts](Chart-gallery#usage-and-costs).

## How the import works

| | |
|---|---|
| First import | The last 30 days. Takes a few minutes, because the days are fetched one by one with a pause in between. |
| After that | Every 3 hours the last stored day and the day before it are imported again, plus any newer days. This picks up corrections by Frank Energie. |
| Newest data | Yesterday. |
| Resolution | Per hour. Quarter-hour data is added up to hours. |
| Days without data | Old days without data are skipped. If yesterday has no data yet, the import stops and tries again 3 hours later. If yesterday's gas or electricity is not complete yet, it tries again every hour until Frank Energie has published it (version 1.8.4 or newer). |
| Errors | A failed call is logged as a warning ("Could not fetch usage and costs for …, stopping the import"). The next run continues where it stopped. |
| Maintenance window | No import between 00:00 and 01:00 UTC, when Frank Energie's service is in maintenance. |
| Recorder | The import needs Home Assistant's recorder. Without it a warning is logged and nothing is imported. |

## Turning it off

Unticking the group stops the import. The statistics already imported are **kept**. Delete them under **Developer tools → Statistics** if you don't want them.

## Good to know

- Each delivery address has its own statistics. After choosing another address with [Reconfigure](Configuration#change-the-delivery-address-reconfigure), new statistics are created for that address; the old ones stay.
- Feed-in and feed-in revenue are positive numbers.
- The statistics come from Frank Energie, not from your own meter. Small differences with a P1 reader are normal.
- The [Daily usage and costs](Sensors#daily-usage-and-costs) sensors show the same data as one total per day. Use the sensors for "what did yesterday cost" and the statistics for the Energy dashboard and history charts.
