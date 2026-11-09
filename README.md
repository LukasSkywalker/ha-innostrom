# Innostrom dynamic tariffs for Home Assistant

The 15-minute electricity prices of your energy provider's dynamic tariff, from
[dynamische-stromtarife.ch](https://portal.dynamische-stromtarife.ch), in Home Assistant. You log in
with your energy provider, so you need no API key.

Supported energy providers: Swisspower, AEW, Alpen Energie Meiringen, EGA, EW Höfe, Energie Thun, IBB.

## Install

Requires Home Assistant 2025.4 or newer.

### Home Assistant 2026.11 and newer: Marketplace

1. Settings → Marketplace → **Add from link** (upper right), enter `LukasSkywalker/ha-innostrom` and select
   **Add**. This repository is not in the Marketplace catalog, so the Marketplace asks you to connect
   GitHub the first time: open the link it shows and enter the code there.
2. Open **Innostrom dynamic tariffs** in the list, select **Install** and confirm the version with
   **Install**. No restart is needed: the setup usually opens right away, so continue with step 2 of
   [Set up](#set-up).

### Home Assistant 2025.4 to 2026.10: HACS

1. HACS → ⋮ → Custom repositories → `https://github.com/LukasSkywalker/ha-innostrom`, type *Integration*.
2. Install **Innostrom dynamic tariffs** and restart Home Assistant.

## Set up

1. Settings → Devices & services → Add integration → **Innostrom dynamic tariffs**.
2. Choose your energy provider. A new window opens its login page.
3. Log in with the details your provider asks for, usually the metering point number (*Messpunktnummer*)
   from your electricity bill, and allow Home Assistant to read your tariff.
4. You come back through My Home Assistant. The first time, it asks for your Home Assistant's address.
5. Choose the metering point whose prices Home Assistant should read, on the page linked in the dialog.
   The dialog finishes on its own once you have chosen one (within ten minutes).

To use a different metering point, remove the integration and add it again: removing it also unlinks
the metering point from your Home Assistant.

## Sensors

| Sensor | |
|---|---|
| Electricity price (*Strompreis*) | What you pay per kWh in the current 15 minutes: energy, grid and fees, in CHF/kWh |
| Feed-in tariff (*Abnahmevergütung*) | What you get per kWh fed into the grid in the current 15 minutes, in CHF/kWh |

The `prices` attribute of each sensor lists every 15-minute slot known so far (`start`, `end`, `price`):
today's, and tomorrow's from 16:00. The prices for tomorrow are loaded at 16:00 Swiss time; if your
provider has not published them yet, Home Assistant tries again every 15 minutes.

**Energy dashboard:** Settings → Dashboards → Energy → Electricity grid → *Use an entity with current
price*: *Electricity price* for consumption and *Feed-in tariff* for return to grid.

## Development

```bash
uv run --with pytest-homeassistant-custom-component python -m pytest -o asyncio_mode=auto tests
```
