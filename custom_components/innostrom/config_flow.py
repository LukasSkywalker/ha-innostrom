"""Log in at the energy provider, then link one of the customer's metering points to this instance."""

import asyncio
import logging

from aiohttp import ClientError

from homeassistant.helpers import config_entry_oauth2_flow, instance_id
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import API, DOMAIN, async_register_brands

# Where the linking page leads back to. Innostrom accepts only https, so it is the integration's page
# through My Home Assistant; the flow does not wait for it, it polls the link status.
RETURN_URI = f"https://my.home-assistant.io/redirect/integration/?domain={DOMAIN}"
LINK_INTERVAL = 5  # seconds between two checks of the link status
LINK_POLLS = 120  # ten minutes to choose a metering point


class OAuth2FlowHandler(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    DOMAIN = DOMAIN
    _link_task: asyncio.Task | None = None

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(__name__)

    async def async_step_user(self, user_input=None):
        async_register_brands(self.hass)
        return await super().async_step_user(user_input)

    async def async_oauth_create_entry(self, data):
        # Innostrom wants a stable id per EMS instance; Home Assistant's survives restores of backups.
        self._data = {**data, "ems_instance_id": await instance_id.async_get(self.hass)}
        try:
            status, self._linking_uri = await self._link_status()
        except ClientError:
            return self.async_abort(reason="cannot_connect")
        if status == "link_unavailable":
            return self.async_abort(reason="no_metering_point")
        if status == "link_established":
            return self.async_create_entry(title=self.flow_impl.name, data=self._data)
        return await self.async_step_link()

    async def async_step_link(self, user_input=None):
        if self._link_task is None:
            self._link_task = self.hass.async_create_task(self._wait_for_link())
        if not self._link_task.done():
            return self.async_show_progress(
                step_id="link",
                progress_action="link",
                progress_task=self._link_task,
                description_placeholders={"url": self._linking_uri},
            )
        return self.async_show_progress_done(next_step_id="finish")

    async def async_step_finish(self, user_input=None):
        if not self._link_task.result():
            return self.async_abort(reason="link_timeout")
        return self.async_create_entry(title=self.flow_impl.name, data=self._data)

    async def _wait_for_link(self) -> bool:
        for _ in range(LINK_POLLS):
            await asyncio.sleep(LINK_INTERVAL)
            try:
                if (await self._link_status())[0] == "link_established":
                    return True
            except ClientError:
                pass  # keep polling, the customer may still be choosing
        return False

    async def _link_status(self) -> tuple[str, str]:
        response = await async_get_clientsession(self.hass).get(
            f"{API}/emsLink",
            params={"ems_instance_id": self._data["ems_instance_id"], "redirect_uri": RETURN_URI},
            headers={"Authorization": f"Bearer {self._data['token']['access_token']}"},
        )
        response.raise_for_status()
        body = await response.json()
        return body["link_status"], body["linking_process_redirect_uri"]
