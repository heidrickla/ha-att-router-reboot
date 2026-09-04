"""Client for the AT&T BGW-series residential gateway web interface.

Everything here is reverse-engineered from a BGW320-500 on firmware 6.35.8 and
kept deliberately small: read the uptime (no login), and reboot (login, then
replay the device's own restart form). No third-party dependency - aiohttp,
hashlib and the standard library cover it.

Two design choices worth stating, because each is load-bearing:

- The reboot REPLAYS the device's form. After logging in, the client fetches
  restart.ha, reads its action, every hidden input and the submit button, and
  posts exactly those back. Hardcoding a body would break on the next firmware
  that renames a field, and a wrong POST to the gateway the whole house routes
  through is not a place to guess.
- The session cookie MUST round-trip. The first GET sets an HttpOnly SessionID;
  without it returning on the next request the gateway serves a form-less
  "enable cookies" stub. aiohttp's cookie jar handles this as long as one
  session object is reused, which is why the client owns its session.
"""

from __future__ import annotations

import hashlib
import logging
import ssl
from html.parser import HTMLParser
from typing import Any

import aiohttp

from .models import BroadbandStats
from .parse import parse_broadband, parse_model, parse_uptime

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=30)


class AttRouterError(Exception):
    """Base error for anything the gateway conversation can raise."""


class AttRouterConnectionError(AttRouterError):
    """The gateway could not be reached at all."""


class AttRouterAuthError(AttRouterError):
    """The access code was rejected."""


class _FormParser(HTMLParser):
    """Pulls the first <form> plus its inputs out of a page.

    A parser rather than a regex because the reboot flow depends on getting
    every hidden field and the exact submit control right, and the BGW markup
    is old enough not to be trusted to a pattern.
    """

    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.fields: dict[str, str] = {}
        self._submit: tuple[str, str] | None = None
        self._in_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "form" and not self._in_form:
            self._in_form = True
            self.action = a.get("action")
        elif tag == "input" and self._in_form:
            name = a.get("name")
            if not name:
                return
            input_type = a.get("type", "text").lower()
            if input_type == "submit":
                # Keep only the first submit; a form posts the one that was
                # clicked, and the reboot page has a single action button.
                if self._submit is None:
                    self._submit = (name, a.get("value", ""))
            else:
                self.fields[name] = a.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._in_form = False

    def finalize(self) -> None:
        if self._submit is not None:
            self.fields.setdefault(self._submit[0], self._submit[1])


def _parse_form(html: str) -> _FormParser:
    parser = _FormParser()
    parser.feed(html)
    parser.finalize()
    return parser


def _legacy_ssl_context() -> ssl.SSLContext:
    """Tolerate the gateway's self-signed certificate.

    Verification is off by default (see const), but even then aiohttp needs a
    context that does not fail the handshake on an untrusted local cert.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class AttRouterClient:
    """Talks to one gateway on behalf of the integration."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        access_code: str,
        *,
        verify_ssl: bool = False,
    ) -> None:
        self._session = session
        self._host = host
        self._access_code = access_code
        self._ssl: ssl.SSLContext | bool = True if verify_ssl else _legacy_ssl_context()

    @property
    def base_url(self) -> str:
        return f"https://{self._host}"

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            # Form actions come from HTML the gateway served. TLS verification
            # is off by default, so a page that pointed the login POST at some
            # other host would carry the hashed access code there. Only follow
            # an absolute action that stays on the gateway itself.
            if path != self.base_url and not path.startswith(f"{self.base_url}/"):
                raise AttRouterError(
                    f"refusing to follow a form action off the gateway: {path}"
                )
            return path
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    async def _get(self, path: str) -> str:
        try:
            async with self._session.get(
                self._url(path), ssl=self._ssl, timeout=_TIMEOUT
            ) as resp:
                if resp.status != 200:
                    raise AttRouterError(f"GET {path} returned HTTP {resp.status}")
                return await resp.text()
        except aiohttp.ClientError as err:
            raise AttRouterConnectionError(str(err)) from err
        except TimeoutError as err:
            raise AttRouterConnectionError(f"timed out reaching {path}") from err

    async def async_get_uptime(self) -> int:
        """Seconds since the gateway last rebooted. No login required."""
        html = await self._get("/cgi-bin/sysinfo.ha")
        uptime = parse_uptime(html)
        if uptime is None:
            # A reachable gateway that does not render the field is a real
            # problem to surface, not a zero to invent.
            raise AttRouterError("sysinfo.ha did not contain an uptime value")
        return uptime

    async def async_get_model(self) -> dict[str, str]:
        """Model, serial, firmware and MAC from sysinfo.ha, best effort."""
        return parse_model(await self._get("/cgi-bin/sysinfo.ha"))

    async def async_get_broadband(self) -> BroadbandStats:
        """WAN status and IPv4 counters. No login required."""
        return parse_broadband(await self._get("/cgi-bin/broadbandstatistics.ha"))

    async def _login(self) -> None:
        """Establish an authenticated session on restart.ha.

        Two round-trips on purpose: the first primes the SessionID cookie so
        the second is served the real form (with its nonce) rather than the
        cookies-disabled stub.
        """
        await self._get("/cgi-bin/restart.ha")
        html = await self._get("/cgi-bin/restart.ha")
        form = _parse_form(html)

        nonce = form.fields.get("nonce")
        if nonce is None:
            # Already authenticated (the reboot form has no nonce-less login),
            # or the markup changed. If a password field is absent we are in.
            if "hashpassword" not in html.lower():
                return
            raise AttRouterError("login form had no nonce")

        # MD5 is the gateway's own login scheme (see the hex_md5 script it
        # ships); there is no choosing a stronger hash on this side.
        hashed = hashlib.md5(
            f"{self._access_code}{nonce}".encode(), usedforsecurity=False
        ).hexdigest()

        payload = {
            "nonce": nonce,
            "password": "*" * len(self._access_code),
            "hashpassword": hashed,
            "Continue": "Continue",
        }
        action = form.action or "/cgi-bin/login.ha"
        try:
            async with self._session.post(
                self._url(action),
                data=payload,
                ssl=self._ssl,
                timeout=_TIMEOUT,
            ) as resp:
                body = await resp.text()
                if resp.status not in (200, 302):
                    raise AttRouterError(f"login returned HTTP {resp.status}")
        except aiohttp.ClientError as err:
            raise AttRouterConnectionError(str(err)) from err
        except TimeoutError as err:
            raise AttRouterConnectionError("timed out logging in") from err

        # A rejected code re-serves the login form; a good one lands on a page
        # without the hash field. This is the only signal the gateway gives.
        if "hashpassword" in body.lower() and "nonce" in body.lower():
            raise AttRouterAuthError("the access code was rejected")

    async def async_verify_access_code(self) -> None:
        """Log in and immediately discard the session. Raises on failure.

        Used by the config flow so a wrong access code is caught while the user
        is still on the form, not on the first reboot weeks later.
        """
        await self._login()

    async def async_reboot(self) -> None:
        """Log in, then replay the gateway's own restart form."""
        await self._login()
        html = await self._get("/cgi-bin/restart.ha")
        form = _parse_form(html)

        if not form.fields:
            raise AttRouterError("the restart page had no form to submit after login")
        # A lingering login form here means the session did not authenticate.
        if "hashpassword" in form.fields:
            raise AttRouterAuthError("still on the login form when trying to reboot")

        action = form.action or "/cgi-bin/restart.ha"
        try:
            async with self._session.post(
                self._url(action),
                data=form.fields,
                ssl=self._ssl,
                timeout=_TIMEOUT,
            ) as resp:
                # The gateway tears the connection down as it reboots, so a
                # dropped response is success, not failure. Only a clean
                # rejection status is an error.
                if resp.status not in (200, 302):
                    raise AttRouterError(f"reboot returned HTTP {resp.status}")
        except (aiohttp.ClientError, TimeoutError):
            _LOGGER.debug("Connection dropped during reboot, as expected")

    async def async_diagnostics(self) -> dict[str, Any]:
        """Non-identifying facts for a diagnostics dump."""
        try:
            uptime = await self.async_get_uptime()
        except AttRouterError:
            uptime = -1
        return {"uptime_seconds": uptime, "host": self._host}
