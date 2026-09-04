"""Client tests: the login hash and the form-replay reboot, no gateway.

    python -m pytest tests/test_api.py

api.py imports aiohttp but no Home Assistant, so it loads by path like the
parser suite. The HTTP layer is faked with a tiny scripted session so the login
handshake and the reboot-by-replay are exercised against known bytes.
"""

import asyncio
import hashlib
import importlib.util
import pathlib
import sys
import types

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

    def get(self, url: str, **kwargs: object) -> _Resp:
        status, text = self._pages.pop(0)
        return _Resp(status, text)

    def post(self, url: str, data: dict, **kwargs: object) -> _Resp:
        self.posts.append((url, data))
        return _Resp(*self._post_result)


def _fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _client(session: _Session, code: str = "1234567890"):
    return api.AttRouterClient(session, "192.168.1.254", code, verify_ssl=False)


def test_login_hash_matches_the_gateway_scheme():
    """hex_md5("abc") self-test the gateway ships, so our hash agrees with it."""
    assert hashlib.md5(b"abc").hexdigest() == "900150983cd24fb0d6963f7d28e17f72"


def test_login_posts_the_md5_of_code_plus_nonce():
    login = _fixture("restart_login.html")
    # The fixture's real nonce, so the assertion is against the device's value.
    nonce = "f7a57648e397b8ba32d851ef76836d6566b561bf0e897cd3bd6eb685ee97bdd4"
    session = _Session(
        pages=[(200, login), (200, login)],
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


def test_a_rejected_code_raises_auth_error():
    login = _fixture("restart_login.html")
    session = _Session(
        pages=[(200, login), (200, login)],
        # A bad code re-serves the login form (nonce + hashpassword present).
        post_result=(200, login),
    )
    client = _client(session)
    try:
        asyncio.run(client.async_verify_access_code())
    except api.AttRouterAuthError:
        return
    raise AssertionError("a rejected code did not raise AttRouterAuthError")


def test_reboot_replays_the_restart_form():
    login = _fixture("restart_login.html")
    reboot_form = (
        '<html><form method="post" action="/cgi-bin/restart.ha">'
        '<input type="hidden" name="nonce" value="abcd" />'
        '<input type="submit" name="Restart" value="Restart" />'
        "</form></html>"
    )
    session = _Session(
        # login GET x2, then the authenticated restart page GET
        pages=[(200, login), (200, login), (200, reboot_form)],
        post_result=(200, "rebooting"),
    )
    client = _client(session)
    asyncio.run(client.async_reboot())

    # Two posts: the login, then the reboot replaying the form's own fields.
    assert len(session.posts) == 2
    url, body = session.posts[1]
    assert url.endswith("/cgi-bin/restart.ha")
    assert body == {"nonce": "abcd", "Restart": "Restart"}


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
                raise api.aiohttp.ClientError("connection reset")
            return _Resp(200, "ok")

    session = _DropSession(
        pages=[(200, login), (200, login), (200, reboot_form)],
        post_result=(200, "ok"),
    )
    client = _client(session)
    # Must not raise.
    asyncio.run(client.async_reboot())
    assert len(session.posts) == 2


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
    try:
        asyncio.run(client.async_verify_access_code())
    except api.AttRouterError as err:
        assert not isinstance(err, api.AttRouterAuthError)
    else:
        raise AssertionError("an off-gateway form action was followed")
    assert session.posts == [], "the hashed access code was posted off-gateway"
