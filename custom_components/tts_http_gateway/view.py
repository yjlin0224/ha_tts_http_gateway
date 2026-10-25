"""HTTP endpoint that clients call with plain GET (or POST) requests."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.http import KEY_HASS

from .const import ENGINE_HEADER, SPEECH_OPTIONS, URL_PATH
from .gateway import DATA_GATEWAYS, NoEngineAvailableError
from .speech import OPTION_EXAMPLES, parse_option, speech_options

_LOGGER = logging.getLogger(__name__)


class TtsGatewayView(HomeAssistantView):
    """Serve /api/tts_http_gateway/<endpoint> for every configured gateway."""

    url = URL_PATH
    name = "api:tts_http_gateway"
    # Clients often can't send Home Assistant tokens; the endpoint's random part is the secret
    requires_auth = False

    async def get(self, request: web.Request, endpoint: str) -> web.StreamResponse:
        return await self._async_handle(request, endpoint, request.query)

    async def post(self, request: web.Request, endpoint: str) -> web.StreamResponse:
        params: dict[str, Any] = dict(request.query)
        if request.content_type == "application/json":
            body: Any = await request.json()
            if not isinstance(body, dict):
                return _error(HTTPStatus.BAD_REQUEST, "The JSON body must be an object")
            params.update(body)
        else:
            params.update(await request.post())
        return await self._async_handle(request, endpoint, params)

    async def _async_handle(
        self, request: web.Request, endpoint: str, params: Mapping[str, Any]
    ) -> web.StreamResponse:
        hass = request.app[KEY_HASS]
        if (gateway := hass.data[DATA_GATEWAYS].get(endpoint)) is None:
            return _error(HTTPStatus.NOT_FOUND, "Not found")

        text = str(params.get("text") or params.get("message") or "").strip()
        if not text:
            return _error(HTTPStatus.BAD_REQUEST, "text is required")

        # Every speech option the request sets wins over the configured one
        overrides: dict[str, str | float] = {}
        for name in SPEECH_OPTIONS:
            if value := str(params.get(name) or "").strip():
                try:
                    overrides[name] = parse_option(name, value)
                except ValueError:
                    return _error(
                        HTTPStatus.BAD_REQUEST, f"{name} must be {OPTION_EXAMPLES[name]}"
                    )
        options = gateway.options.merged(speech_options(overrides))

        try:
            result = await gateway.async_synthesize(
                text,
                options=options,
                language=str(params.get("language") or "").strip() or gateway.language,
            )
        except NoEngineAvailableError as err:
            return _error(HTTPStatus.SERVICE_UNAVAILABLE, str(err))

        response = web.StreamResponse(headers={ENGINE_HEADER: result.engine})
        response.content_type = result.content_type
        response.headers["Cache-Control"] = "no-store"
        try:
            await response.prepare(request)
            await response.write(result.first_chunk)
            while True:
                try:
                    chunk = await anext(result.chunks)
                except StopAsyncIteration:
                    break
                except Exception as err:  # noqa: BLE001  # engines raise anything
                    # The status is already sent, so end the audio early instead of failing
                    _LOGGER.warning("%s failed after its audio started: %s", result.engine, err)
                    gateway.async_record_stream_error(result.engine, err)
                    break
                await response.write(chunk)
            await response.write_eof()
        finally:
            await result.chunks.aclose()
        return response


def _error(status: HTTPStatus, message: str) -> web.Response:
    return web.Response(status=status, text=message)
