"""Turn the gateway's HTML pages into typed data.

Home-Assistant-free on purpose: this is where the fragile firmware-scraping
lives, and it is tested against saved HTML without a running gateway. Every
extractor returns None on a miss so a markup change on one row cannot take out
the whole page.
"""

from __future__ import annotations

import re

from .models import BroadbandStats

_UPTIME_RE = re.compile(
    r"Time Since Last Reboot.*?<td[^>]*>\s*(\d+)\s*</td>",
    re.IGNORECASE | re.DOTALL,
)


def _cells(html: str) -> list[str]:
    """Flatten a page to its non-empty cell texts, in order."""
    out = []
    for chunk in re.split(r"<[^>]+>", html):
        text = re.sub(r"\s+", " ", chunk).strip()
        if text and text != "&nbsp;":
            out.append(text)
    return out


def _value_after(cells: list[str], label: str) -> str | None:
    """The cell immediately after the first cell equal to `label`.

    Exact match, not substring: the pages repeat short labels ("State",
    "Transmit Packets") in different sections, and a substring match would grab
    the help-text paragraph that echoes the label with a trailing colon.
    """
    for i, cell in enumerate(cells):
        if cell.lower() == label.lower() and i + 1 < len(cells):
            return cells[i + 1]
    return None


def _int_after(cells: list[str], label: str) -> int | None:
    raw = _value_after(cells, label)
    if raw is None:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def parse_uptime(html: str) -> int | None:
    match = _UPTIME_RE.search(html)
    return int(match.group(1)) if match else None


def parse_model(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for label, key in (
        ("Model Number", "model"),
        ("Serial Number", "serial"),
        ("Software Version", "firmware"),
        ("MAC Address", "mac"),
    ):
        m = re.search(
            rf"{re.escape(label)}.*?<td[^>]*>\s*([^<]+?)\s*</td>",
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            out[key] = m.group(1).strip()
    return out


def parse_broadband(html: str) -> BroadbandStats:
    """The broadband statistics page.

    The IPv4 counters must be read from before the "IPv6 Statistics" heading,
    because the IPv6 section repeats the same "Transmit Packets" style labels
    and taking the first exact match would otherwise be ambiguous. Slicing at
    the heading keeps the counters unambiguously IPv4.
    """
    conn = _value_after(_cells(html), "Broadband Connection")
    source = _value_after(_cells(html), "Broadband Connection Source")
    ipv4 = _value_after(_cells(html), "Broadband IPv4 Address")
    line_state = _value_after(_cells(html), "Line State")
    speed = _int_after(_cells(html), "Current Speed (Mbps)")
    duplex = _value_after(_cells(html), "Current Duplex")

    ipv4_section = re.split(
        r"IPv6\s+Statistics", html, maxsplit=1, flags=re.IGNORECASE
    )[0]
    ipv4_cells = _cells(ipv4_section)

    return BroadbandStats(
        connection_up=None if conn is None else conn.strip().lower() == "up",
        connection_source=source,
        ipv4_address=ipv4,
        line_state=line_state,
        speed_mbps=speed,
        duplex=duplex,
        rx_bytes=_int_after(ipv4_cells, "Receive Bytes"),
        tx_bytes=_int_after(ipv4_cells, "Transmit Bytes"),
        rx_packets=_int_after(ipv4_cells, "Receive Packets"),
        tx_packets=_int_after(ipv4_cells, "Transmit Packets"),
        rx_errors=_int_after(ipv4_cells, "Receive Errors"),
        tx_errors=_int_after(ipv4_cells, "Transmit Errors"),
    )
