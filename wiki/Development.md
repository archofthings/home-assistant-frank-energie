# Development

## Set up

Python 3.14.

```bash
python3.14 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Run the checks like CI does:

```bash
.venv/bin/flake8 . --count --max-complexity=10 --max-line-length=120 --statistics
```

```bash
.venv/bin/pytest
```

The tests mock the Frank Energie API completely; they never call the real service.

## Code map

Everything is in `custom_components/frank_energie/`.

| File | What it does |
|---|---|
| `__init__.py` | Sets up an entry, removes entities of disabled sensor groups, creates the coordinators, registers the action |
| `config_flow.py` | Login, address choice, re-authentication, reconfigure and the two options pages |
| `coordinator.py` | Fetches prices, monthly costs and invoices; public fallback; token renewal; stale data |
| `sensor.py` | All sensors |
| `binary_sensor.py` | *Tomorrow's prices available* and the price analysis binary sensors |
| `analysis.py` | Pure calculations: levels, cheapest period, windows, solar per slot |
| `price_analysis.py` | Coordinator that runs the analysis every quarter hour and on new prices |
| `solar_forecast.py` | Reads the solar forecast of another integration, best effort |
| `usage.py` | Coordinator for daily and monthly usage and costs |
| `contract.py` | Coordinator for the contract's price resolution |
| `energy_statistics.py` | Imports hourly usage and costs as long-term statistics |
| `services.py`, `services.yaml` | The `frank_energie.get_prices` action |
| `diagnostics.py` | Redacted diagnostics download |
| `sites.py` | Delivery address filtering and names |
| `device.py` | The two devices (their identifiers must not change) |
| `const.py` | Constants, option keys, defaults and the sensor groups |
| `strings.json`, `translations/` | UI texts in English and Dutch (keep the three files in sync) |

API client: [python-frank-energie](https://github.com/HiDiHo01/python-frank-energie) by [@HiDiHo01](https://github.com/HiDiHo01) ([PyPI](https://pypi.org/project/python-frank-energie/)), version pinned in `manifest.json`. Problems in the communication with Frank Energie itself are best reported there.

## Rules of the house

- Entity unique IDs and device identifiers never change, so upgrades keep entity IDs and history.
- A new sensor belongs to a sensor group and is off for existing installations.
- Never log tokens, passwords or other credentials.
- flake8: line length 120, complexity 10.
- Keep tests lean: one test for the main behaviour, plus the edge cases that matter.

## Releases

Publishing a GitHub release runs a workflow that sets the version in `manifest.json` from the tag and uploads `frank_energie.zip`, the file HACS installs.

## This wiki

The pages are kept in the `wiki/` folder of the repository and copied to the GitHub wiki. To change a page, change it there in a pull request.

## Contributing

Issues and pull requests are welcome at [archofthings/home-assistant-frank-energie](https://github.com/archofthings/home-assistant-frank-energie). For a bigger change, open an issue first to discuss it.
