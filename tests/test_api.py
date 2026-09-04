"""Client tests: the login hash and the form-replay reboot, no gateway.

    python -m pytest tests/test_api.py

api.py imports aiohttp but no Home Assistant, so it loads by path like the
parser suite. The HTTP layer is faked with a tiny scripted session so the login
handshake and the reboot-by-replay are exercised against known bytes. The one
real aiohttp object under test is the cookie jar, because the whole login
depends on how it treats an IP-address host.
"""

import asyncio
import hashlib
import importlib.util
import pathlib
import sys
import types

import aiohttp
import pytest
from yarl import URL

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMP = ROOT / "custom_components" / "att_router_reboot"
FIX = ROOT / "tests" / "fixtures"

_pkg = types.ModuleType("att_router_reboot")
_pkg.__path__ = [str(COMP)]
sys.modules["att_router_reboot"] = _pkg


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"att_router_reboot.{name}", COMP / f"{name}.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"att_router_reboot.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


_load("models")
_load("parse")
api = _load("api")

# The gateway's own restart form, as served once the session is logged in.
RESTART_FORM = (
    '<html><form method="post" action="/cgi-bin/restart.ha">'
    '<input type="hidden" name="nonce" value="abcd" />'
    '<input type="submit" name="Restart" value="Restart" />'
    "</form></html>"
)
# What the gateway serves when the SessionID cookie did not come back.
COOKIE_STUB = "<html><body><p>Please enable cookies in your browser.</p></body></html>"


class _Resp:
    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self) -> "_Resp":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _Session:
    """A scripted aiohttp stand-in. GETs pop from `pages`; POSTs are recorded."""

    def __init__(self, pages: list[tuple[int, str]], post_result: tuple[int, str]):
        self._pages = list(pages)
        self._post_result = post_result
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[str] = []

    def get(self, url: str, **kwargs: object) -> _Resp:
        self.gets.append(url)
        status, text = self._pages.pop(0)
        return _Resp(status, text)

    def post(self, url: str, data: dict, **kwargs: object) -> _Resp:
        self.posts.append((url, data))
        return _Resp(*self._post_result)


def _fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _client(session: _Session, code: str = "1234567890"):
    return api.AttRouterClient(session, "192.168.1.254", code)


def test_login_hash_matches_the_gateway_scheme():
    """hex_md5("abc") self-test the gateway ships, so our hash agrees with it."""
    assert hashlib.md5(b"abc").hexdigest() == "900150983cd24fb0d6963f7d28e17f72"


def test_login_posts_the_md5_of_code_plus_nonce():
    login = _fixture("restart_login.html")
    # The fixture's real nonce, so the assertion is against the device's value.
    nonce = "f7a57648e397b8ba32d851ef76836d6566b561bf0e897cd3bd6eb685ee97bdd4"
    session = _Session(
        pages=[(200, login), (200, login), (200, RESTART_FORM)],
        post_result=(200, "<html>welcome</html>"),
    )
    client = _client(session, "secret42")
    asyncio.run(client.async_verify_access_code())

    assert session.posts, "login never posted"
    url, body = session.posts[0]
    assert url.endswith("/cgi-bin/login.ha")
    assert body["hashpassword"] == hashlib.md5(f"secret42{nonce}".encode()).hexdigest()
    # The clear password is masked, never sent in the clear.
    assert set(body["password"]) == {"*"}


def test_the_client_leaves_tls_policy_to_the_session():
    """No per-request ssl argument: the session's connector decides, which is
    how Home Assistant's no-verify context reaches the gateway."""
    login = _fixture("restart_login.html")

    class _Strict(_Session):
        def get(self, url: str, **kwargs: object) -> _Resp:
            assert "ssl" not in kwargs, kwargs
            return super().get(url, **kwargs)

        def post(self, url: str, data: dict, **kwargs: object) -> _Resp:
            assert "ssl" not in kwargs, kwargs
            return super().post(url, data, **kwargs)

    session = _Strict(
        pages=[(200, login), (200, login), (200, RESTART_FORM)],
        post_result=(200, "ok"),
    )
    asyncio.run(_client(session).async_verify_access_code())


def test_a_rejected_code_raises_auth_error():
    login = _fixture("restart_login.html")
    session = _Session(
        pages=[(200, login), (200, login)],
        # A bad code re-serves the login form (nonce + hashpassword present).
        post_result=(200, login),
    )
    with pytest.raises(api.AttRouterAuthError):
        asyncio.run(_client(session).async_verify_access_code())


def test_a_login_that_lands_back_on_the_login_form_is_an_auth_error():
    """The POST answered with something bland, but restart.ha still wants a
    code: the session did not authenticate."""
    login = _fixture("restart_login.html")
    session = _Session(
        pages=[(200, login), (200, login), (200, login)],
        post_result=(200, "<html>ok</html>"),
    )
    with pytest.raises(api.AttRouterAuthError):
        asyncio.run(_client(session).async_verify_access_code())


def test_login_needs_the_restart_form_as_proof_not_just_a_missing_password_field():
    """The cookies-disabled stub has no nonce and no hashpassword. It used to
    read as 'already logged in'; now it is the failure it is, and not an auth
    failure, since no code was ever checked."""
    session = _Session(
        pages=[(200, COOKIE_STUB), (200, COOKIE_STUB)],
        post_result=(200, "never"),
    )
    with pytest.raises(api.AttRouterError) as info:
        asyncio.run(_client(session).async_verify_access_code())
    assert not isinstance(info.value, api.AttRouterAuthError)
    assert "cookie" in str(info.value)
    assert session.posts == [], "posted a login with no nonce to hash against"


def test_a_stub_after_the_login_post_is_not_success():
    login = _fixture("restart_login.html")
    session = _Session(
        pages=[(200, login), (200, login), (200, COOKIE_STUB)],
        post_result=(200, "<html>ok</html>"),
    )
    with pytest.raises(api.AttRouterError) as info:
        asyncio.run(_client(session).async_verify_access_code())
    assert not isinstance(info.value, api.AttRouterAuthError)


def test_an_already_authenticated_session_skips_the_login_post():
    """restart.ha served the restart form straight away: nothing to post."""
    session = _Session(
        pages=[(200, RESTART_FORM), (200, RESTART_FORM)],
        post_result=(200, "never"),
    )
    asyncio.run(_client(session).async_verify_access_code())
    assert session.posts == []


def test_a_login_form_without_a_nonce_is_an_error():
    broken = '<form action="/cgi-bin/login.ha"><input name="hashpassword" /></form>'
    session = _Session(pages=[(200, broken), (200, broken)], post_result=(200, ""))
    with pytest.raises(api.AttRouterError, match="nonce"):
        asyncio.run(_client(session).async_verify_access_code())


def test_a_non_200_page_is_an_error_not_a_connection_error():
    session = _Session(pages=[(500, "boom")], post_result=(200, ""))
    with pytest.raises(api.AttRouterError) as info:
        asyncio.run(_client(session).async_get_uptime())
    assert not isinstance(info.value, api.AttRouterConnectionError)
    assert "HTTP 500" in str(info.value)


def test_transport_failures_are_connection_errors():
    class _Down(_Session):
        def get(self, url: str, **kwargs: object) -> _Resp:
            raise aiohttp.ClientConnectionError("refused")

    class _Slow(_Session):
        def get(self, url: str, **kwargs: object) -> _Resp:
            raise TimeoutError

    for session in (_Down([], (200, "")), _Slow([], (200, ""))):
        with pytest.raises(api.AttRouterConnectionError):
            asyncio.run(_client(session).async_get_uptime())


def test_uptime_is_an_error_when_the_page_has_no_value():
    session = _Session(pages=[(200, "<html>maintenance</html>")], post_result=(200, ""))
    with pytest.raises(api.AttRouterError, match="uptime"):
        asyncio.run(_client(session).async_get_uptime())


def test_model_and_broadband_are_read_from_the_real_pages():
    session = _Session(
        pages=[
            (200, _fixture("sysinfo.html")),
            (200, _fixture("broadbandstatistics.html")),
        ],
        post_result=(200, ""),
    )
    client = _client(session)
    info = asyncio.run(client.async_get_model())
    assert info["model"] == "BGW320-500"
    stats = asyncio.run(client.async_get_broadband())
    assert stats.connection_up is True


def test_reboot_replays_the_restart_form():
    login = _fixture("restart_login.html")
    session = _Session(
        # login GET x2, then the authenticated restart page GET
        pages=[(200, login), (200, login), (200, RESTART_FORM)],
        post_result=(200, "rebooting"),
    )
    client = _client(session)
    asyncio.run(client.async_reboot())

    # Two posts: the login, then the reboot replaying the form's own fields.
    assert len(session.posts) == 2
    url, body = session.posts[1]
    assert url.endswith("/cgi-bin/restart.ha")
    assert body == {"nonce": "abcd", "Restart": "Restart"}
    # Login primes the cookie, reads the form, then proves the login: 3 GETs.
    assert len(session.gets) == 3


def test_reboot_treats_a_dropped_connection_as_success():
    """The gateway tears the socket down as it reboots; that is not a failure."""
    login = _fixture("restart_login.html")
    reboot_form = (
        '<html><form action="/cgi-bin/restart.ha">'
        '<input type="submit" name="Restart" value="Restart" />'
        "</form></html>"
    )

    class _DropSession(_Session):
        def post(self, url: str, data: dict, **kwargs: object) -> _Resp:
            self.posts.append((url, data))
            if len(self.posts) == 2:
                raise aiohttp.ClientError("connection reset")
            return _Resp(200, "ok")

    session = _DropSession(
        pages=[(200, login), (200, login), (200, reboot_form)],
        post_result=(200, "ok"),
    )
    client = _client(session)
    # Must not raise.
    asyncio.run(client.async_reboot())
    assert len(session.posts) == 2


def test_reboot_rejected_with_a_clean_status_is_an_error():
    login = _fixture("restart_login.html")

    class _Refuse(_Session):
        def post(self, url: str, data: dict, **kwargs: object) -> _Resp:
            self.posts.append((url, data))
            return _Resp(403, "no") if len(self.posts) == 2 else _Resp(200, "ok")

    session = _Refuse(
        pages=[(200, login), (200, login), (200, RESTART_FORM)],
        post_result=(200, "ok"),
    )
    with pytest.raises(api.AttRouterError, match="HTTP 403"):
        asyncio.run(_client(session).async_reboot())


def test_login_refuses_a_form_action_off_the_gateway():
    """A page that points the login POST elsewhere must not get the hash."""
    login = _fixture("restart_login.html").replace(
        'action="/cgi-bin/login.ha"', 'action="https://203.0.113.99/steal"'
    )
    assert "203.0.113.99" in login, "fixture no longer has the expected action"
    session = _Session(
        pages=[(200, login), (200, login)],
        post_result=(200, "<html>welcome</html>"),
    )
    client = _client(session, "secret42")
    with pytest.raises(api.AttRouterError) as info:
        asyncio.run(client.async_verify_access_code())
    assert not isinstance(info.value, api.AttRouterAuthError)
    assert session.posts == [], "the hashed access code was posted off-gateway"


def test_an_absolute_action_on_the_gateway_itself_is_followed():
    login = _fixture("restart_login.html").replace(
        'action="/cgi-bin/login.ha"', 'action="https://192.168.1.254/cgi-bin/login.ha"'
    )
    session = _Session(
        pages=[(200, login), (200, login), (200, RESTART_FORM)],
        post_result=(200, "ok"),
    )
    asyncio.run(_client(session).async_verify_access_code())
    assert session.posts[0][0] == "https://192.168.1.254/cgi-bin/login.ha"


def test_the_default_cookie_jar_drops_the_gateway_cookie_and_the_unsafe_one_keeps_it():
    """The load-bearing aiohttp fact, checked against the real jar.

    The gateway is reached by IP and sets an HttpOnly SessionID. aiohttp's
    default jar refuses cookies from IP hosts, which is exactly the cookieless
    second request that earns the "enable cookies" stub. The hostname case is
    the positive control: the same default jar keeps that cookie.
    """
    gateway = URL("https://192.168.1.254/cgi-bin/restart.ha")
    by_name = URL("https://gateway.example/cgi-bin/restart.ha")

    async def run() -> tuple[set[str], set[str], set[str]]:
        default = aiohttp.CookieJar()
        default.update_cookies({"SessionID": "abc"}, gateway)
        default.update_cookies({"SessionID": "abc"}, by_name)
        unsafe = aiohttp.CookieJar(unsafe=True)
        unsafe.update_cookies({"SessionID": "abc"}, gateway)
        return (
            set(default.filter_cookies(gateway)),
            set(default.filter_cookies(by_name)),
            set(unsafe.filter_cookies(gateway)),
        )

    default_ip, default_name, unsafe_ip = asyncio.run(run())
    assert default_ip == set(), "aiohttp now keeps IP cookies; revisit unsafe=True"
    assert default_name == {"SessionID"}
    assert unsafe_ip == {"SessionID"}
