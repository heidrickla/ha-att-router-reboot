"""Parser tests against real BGW320-500 HTML.

    python -m pytest tests/test_parse.py

Loads parse.py and models.py by path so the suite runs on a bare interpreter
with no Home Assistant - the parsing is the fragile, firmware-facing part and
deserves to be tested where a gateway is not needed. The fixtures are real
pages from a BGW320-500 (firmware 6.35.8) with the household's WAN IP, IPv6,
MAC and serial replaced by documentation-range placeholders.
"""

import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMP = ROOT / "custom_components" / "att_router_reboot"
FIX = ROOT / "tests" / "fixtures"

# A stand-in package so parse.py's `from .models import ...` resolves without
# executing the real __init__.py, which imports Home Assistant.
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


models = _load("models")
parse = _load("parse")


def _fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_uptime_is_read_as_seconds():
    assert parse.parse_uptime(_fixture("sysinfo.html")) == 1085939


def test_uptime_is_none_when_the_field_is_absent():
    assert parse.parse_uptime("<html><body>nothing here</body></html>") is None


def test_model_fields_are_read():
    info = parse.parse_model(_fixture("sysinfo.html"))
    assert info["model"] == "BGW320-500"
    assert info["firmware"] == "6.35.8"
    assert "mac" in info and "serial" in info


def test_broadband_status_and_identity():
    b = parse.parse_broadband(_fixture("broadbandstatistics.html"))
    assert b.connection_up is True
    assert b.connection_source == "ETHERNET"
    assert b.ipv4_address == "203.0.113.10"
    assert b.line_state == "Up"
    assert b.speed_mbps == 1000
    assert b.duplex == "full"


def test_broadband_counters_are_the_ipv4_ones():
    """The IPv6 section repeats these labels; the IPv4 values must win.

    The transmit-packets value in the IPv6 section on this unit is a
    13-digit number, so if the slice were wrong tx_packets would be wildly
    larger than the byte count. Pinning the exact IPv4 values guards that.
    """
    b = parse.parse_broadband(_fixture("broadbandstatistics.html"))
    assert b.rx_bytes == 299042212153
    assert b.tx_bytes == 193899216140
    assert b.rx_packets == 295431047
    assert b.tx_packets == 212351256
    assert b.rx_errors == 0
    assert b.tx_errors == 0


def test_broadband_degrades_to_none_on_unfamiliar_markup():
    b = parse.parse_broadband("<html><body><p>maintenance</p></body></html>")
    assert b.connection_up is None
    assert b.ipv4_address is None
    assert b.rx_bytes is None


def test_a_down_connection_reads_false_not_none():
    html = "<table><tr><td>Broadband Connection</td><td>Down</td></tr></table>"
    assert parse.parse_broadband(html).connection_up is False
