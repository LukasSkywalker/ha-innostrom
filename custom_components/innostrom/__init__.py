"""Dynamic electricity tariffs from Innostrom (dynamische-stromtarife.ch)."""

from datetime import datetime, time, timedelta
import logging

from aiohttp import ClientError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

DOMAIN = "innostrom"
API = "https://portal.dynamische-stromtarife.ch/api/v2"
# The authentik provider hems-oidc-homeassistant-prod. A *public* client: the integration's source is
# public, so it holds no secret; PKCE and the strict redirect URI to my.home-assistant.io protect the codes.
CLIENT_ID = "Q8N7EqAXZHhEM0AzPASS6xDxIvcQ1RozBjwS3F4o"
# One authentik brand per energy provider: the same client logs in at each, and a connection must keep
# refreshing at the brand it was made at, because the brand's host is part of the token's issuer.
BRANDS = {"swisspower": "Swisspower", "aewaargau": "AEW", "aemeiringen": "Alpen Energie Meiringen", "egaettenschwil": "EGA", "ewhoefe": "EW Höfe", "enthun": "Energie Thun", "ibbrugg": "IBB" }
# Components of tariff_type=all, each one sensor, named in translations/.
PRICES = ("integrated", "feed_in")
ZURICH = dt_util.get_time_zone("Europe/Zurich")
# Innostrom serves tomorrow's prices from 16:00 Zurich time. The seconds cover the coordinator
# scheduling up to a second early.
PUBLISH = time(16, 0, 10)
# How often to try again while tomorrow's prices are not computed yet (they can take until 18:00).
RETRY = timedelta(minutes=15)


class Brand(config_entry_oauth2_flow.LocalOAuth2ImplementationWithPkce):
    """Logs in at an energy provider's authentik brand."""

    def __init__(self, hass: HomeAssistant, key: str, name: str) -> None:
        url = f"https://{key}.authentik.code-fabrik.ch/application/o"
        super().__init__(hass, key, CLIENT_ID, f"{url}/authorize/", f"{url}/token/")
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def extra_authorize_data(self) -> dict:
        # offline_access, or authentik issues no refresh token.
        return {**super().extra_authorize_data, "scope": "openid profile offline_access"}


@callback
def async_register_brands(hass: HomeAssistant) -> None:
    """Registered from the config flow too: a first setup runs before async_setup_entry."""
    for key, name in BRANDS.items():
        config_entry_oauth2_flow.async_register_implementation(hass, DOMAIN, Brand(hass, key, name))


def next_refresh(now: datetime, has_tomorrow: bool) -> datetime | None:
    """The next 16:00 that brings new prices, or None to retry soon. `now` is in Zurich time."""
    publish = datetime.combine(now.date(), PUBLISH, ZURICH)
    if now >= publish and has_tomorrow:
        publish += timedelta(days=1)  # wall-clock arithmetic: stays 16:00 across DST changes
    return publish if now < publish else None


class Coordinator(DataUpdateCoordinator[list[dict]]):
    """Today's and tomorrow's 15-minute prices of the metering point linked to this instance."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, session) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=RETRY)
        self.session = session

    async def _async_update_data(self) -> list[dict]:
        self.update_interval = RETRY  # kept if this request fails
        now = dt_util.now(ZURICH)
        today = datetime.combine(now.date(), time(), ZURICH)
        tomorrow = today + timedelta(days=1)
        response = await self.session.async_request(
            "get",
            f"{API}/metering_code",
            params={
                "ems_instance_id": self.config_entry.data["ems_instance_id"],
                "tariff_type": "all",
                "start_timestamp": today.isoformat(),
                "end_timestamp": (tomorrow + timedelta(days=1)).isoformat(),
            },
        )
        response.raise_for_status()
        slots = [
            {
                "start": dt_util.parse_datetime(slot["start_timestamp"]),
                "end": dt_util.parse_datetime(slot["end_timestamp"]),
                **{key: slot[key][0]["value"] for key in PRICES},
            }
            for slot in (await response.json())["prices"]
        ]
        if at := next_refresh(now, any(slot["start"] >= tomorrow for slot in slots)):
            # Subtracted in UTC: aware datetimes in the same zone subtract as wall-clock times.
            self.update_interval = dt_util.as_utc(at) - dt_util.utcnow()
        return slots


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    async_register_brands(hass)
    implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(hass, entry)
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    coordinator = entry.runtime_data = Coordinator(hass, entry, session)
    await coordinator.async_config_entry_first_refresh()
    # The current price changes every quarter hour, not only when new prices arrive.
    entry.async_on_unload(
        async_track_time_change(
            hass, callback(lambda _: coordinator.async_update_listeners()), minute="/15", second=0
        )
    )
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Unlink the metering point, so that adding the integration again lets the customer choose one."""
    async_register_brands(hass)  # also when the entry never loaded
    implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(hass, entry)
    try:
        # Refreshed by hand: the entry is already gone, so OAuth2Session could not store a new token.
        token = await implementation.async_refresh_token(entry.data["token"])
        response = await config_entry_oauth2_flow.async_oauth2_request(
            hass, token, "delete", f"{API}/emsLink", params={"ems_instance_id": entry.data["ems_instance_id"]}
        )
        response.raise_for_status()
    except (ClientError, TimeoutError) as err:
        _LOGGER.warning("Could not unlink the metering point from this instance: %s", err)
