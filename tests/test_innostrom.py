"""uv run --with pytest-homeassistant-custom-component python -m pytest -o asyncio_mode=auto tests"""

from datetime import datetime, timedelta
from unittest.mock import patch

from homeassistant.helpers.config_entry_oauth2_flow import MY_AUTH_CALLBACK_PATH
from homeassistant.util import dt as dt_util

from custom_components.innostrom import API, ZURICH, next_refresh

AUTHENTIK = "https://enthun.authentik.code-fabrik.ch/application/o"


def test_next_refresh():
    def at(day, hour, minute=0):
        return datetime(2027, 3, day, hour, minute, tzinfo=ZURICH)

    assert next_refresh(at(27, 10), has_tomorrow=False) == at(27, 16).replace(second=10)
    assert next_refresh(at(27, 16, 5), has_tomorrow=False) is None  # not published yet: retry
    # Across the switch to summer time on 28 March: still 16:00, which is 23 hours later, not 24.
    after = next_refresh(at(27, 16, 5), has_tomorrow=True)
    assert after == at(28, 16).replace(second=10)
    assert dt_util.as_utc(after) - dt_util.as_utc(at(27, 16, 5)) == timedelta(hours=22, minutes=55, seconds=10)


async def test_login_link_and_prices(hass, aioclient_mock, enable_custom_integrations, freezer):
    freezer.move_to("2026-11-09T15:00:00+01:00")
    hass.config.components.add("my")  # its redirect URI is the one registered in authentik
    aioclient_mock.post(f"{AUTHENTIK}/token/", json={
        "access_token": "at", "refresh_token": "rt", "token_type": "Bearer", "expires_in": 86400,
    })
    link = lambda status: aioclient_mock.get(f"{API}/emsLink", json={
        "link_status": status, "linking_process_redirect_uri": "https://portal/ems_link/new?…",
    })
    link("link_required")

    flows = hass.config_entries.flow
    result = await flows.async_init("innostrom", context={"source": "user"})
    assert result["step_id"] == "pick_implementation"
    result = await flows.async_configure(result["flow_id"], {"implementation": "enthun"})
    assert result["type"] == "external"
    assert result["url"].startswith(f"{AUTHENTIK}/authorize/?")
    assert "code_challenge=" in result["url"] and "offline_access" in result["url"]

    flow_id = result["flow_id"]
    state = {"flow_id": flow_id, "redirect_uri": MY_AUTH_CALLBACK_PATH}
    with patch("custom_components.innostrom.config_flow.LINK_INTERVAL", 0):
        await flows.async_configure(flow_id, {"code": "c0de", "state": state})  # what the callback view does
        result = await flows.async_configure(flow_id)
        assert result["type"] == "progress"
        aioclient_mock.clear_requests()  # the customer chose a metering point
        link("link_established")
        aioclient_mock.get(f"{API}/metering_code", json={"status": "ok", "prices": [{
            "start_timestamp": "2026-11-09T15:00:00+01:00", "end_timestamp": "2026-11-09T15:15:00+01:00",
            "integrated": [{"value": 0.2512, "unit": "CHF_kWh", "component": "work"}],
            "feed_in": [{"value": 0.08, "unit": "CHF_kWh", "component": "work"}],
        }]})
        await hass.async_block_till_done()
        result = await flows.async_configure(flow_id)
    assert result["type"] == "create_entry"
    assert result["title"] == "Energie Thun"
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries("innostrom")[0]
    assert entry.data["auth_implementation"] == "enthun"
    assert hass.states.get("sensor.electricity_price").state == "0.2512"
    assert hass.states.get("sensor.feed_in_tariff").state == "0.08"
    # Before 16:00 without tomorrow's prices: the next fetch is today at 16:00, not a retry.
    assert entry.runtime_data.update_interval == timedelta(hours=1, seconds=10)

    freezer.move_to("2026-11-09T15:15:00+01:00")  # past the only slot
    entry.runtime_data.async_update_listeners()
    assert hass.states.get("sensor.electricity_price").state == "unavailable"
