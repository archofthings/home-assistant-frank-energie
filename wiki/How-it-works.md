# How it works

When data is fetched, where it comes from and what happens when Frank Energie's service has a problem.

## Update schedule

| Data | Fetched | Notes |
|---|---|---|
| Prices of today and tomorrow | Every 60 minutes | Every **15 minutes** from 12:00 (Dutch time) until tomorrow's electricity prices are there |
| Monthly costs and invoices 🔑 | Together with the prices | When logged in |
| Daily and monthly usage and costs 🔑 | Every 3 hours | Groups *Daily usage and costs*, *Monthly usage and costs* |
| Contract price resolution 🔑 | Every 6 hours | Group *Costs and invoices* |
| Energy dashboard statistics 🔑 | Every 3 hours | Group *Energy dashboard statistics* |
| Price analysis | Every quarter hour, and when new prices arrive | Calculated locally; only the solar forecast is read from another integration |

Between fetches the **sensor states still change**: at every quarter hour (:00, :15, :30, :45) the price sensors move to the current slot, using the prices already fetched.

Frank Energie usually publishes tomorrow's prices around 13:00. Because of the faster checks after 12:00 they appear in Home Assistant within 15 minutes of publication.

Between **00:00 and 01:00 UTC** Frank Energie's service has a daily maintenance window. The integration does not fetch then and keeps showing the prices it has.

## Where the prices come from

| Entry | Prices |
|---|---|
| Not logged in | Frank Energie's public prices for the Netherlands, per quarter-hour or per hour ([your choice](Configuration#price-resolution)) |
| Logged in | The prices of your own contract and address, in your contract's resolution. Belgian customers get Belgian prices. |

If your account has no prices for electricity or gas on a day (for example without a gas contract), the public prices are used for that part, so the sensors keep working.

## Days, time zones and daylight saving

- "Today" and "tomorrow" are **Dutch calendar days** (Europe/Amsterdam), because that is how the energy market works. This matters only when your Home Assistant is in another time zone.
- A normal day has 96 quarter-hour or 24 hourly electricity prices. On the day the clock goes forward there are 92 or 23, on the day it goes back 100 or 25.
- How times are **written** in attributes is your choice, see [Time zone for price times](Configuration#time-zone-for-price-times).

## When something goes wrong

| Situation | What the integration does |
|---|---|
| Frank Energie can't be reached or returns an error | Keeps the last prices as long as they still contain upcoming prices, and logs a warning. Tries again at the next update. |
| No usable prices left | Entities become unavailable until a fetch succeeds. |
| Monthly costs or invoices fail, prices work | Prices keep updating. The cost and invoice sensors keep their previous value; a warning "Could not fetch …" is logged. |
| Daily or monthly usage fails | The other one still updates. The failed one keeps its previous value, but last month's numbers are never shown as this month's. |
| Access token expired | Renewed automatically and saved. You notice nothing. |
| Renewal refused | Home Assistant asks you to [re-authenticate](Configuration#re-authenticate). |
| Solar forecast integration slow or broken | The price analysis continues without solar after at most 10 seconds. |
| Home Assistant starts while Frank Energie is down | The integration retries by itself until it succeeds. |

## Requests to Frank Energie

The integration is careful with Frank Energie's service:

| Setup | Requests per day (about) |
|---|---|
| Not logged in | 50 to 60 |
| Logged in, all groups on | 135 to 165 |

The usage, statistics and price resolution requests are only made when their sensor group is on. The first import of the Energy dashboard statistics fetches 30 days with a pause of 5 seconds between days.

## Privacy and security

- Your **password is not stored**. Home Assistant keeps your e-mail address, an access token and a refresh token in its own configuration storage.
- The integration talks only to Frank Energie's service.
- The integration never writes tokens or passwords to the log.
- The [diagnostics download](Troubleshooting#diagnostics) removes tokens, e-mail address, address and site reference.
- The integration only **reads** data. It cannot change your contract or anything else in your account.
