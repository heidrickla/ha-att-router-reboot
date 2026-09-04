"""Typed shapes for what the gateway reports.

Kept free of Home Assistant imports so the parsing that fills them can be
tested on a bare interpreter against saved HTML.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BroadbandStats:
    """The broadband (WAN) statistics page, parsed.

    Every field is optional: the page is scraped from firmware-authored HTML,
    so a renamed row must degrade to None rather than break the whole poll.
    """

    connection_up: bool | None = None
    connection_source: str | None = None
    ipv4_address: str | None = None
    line_state: str | None = None
    speed_mbps: int | None = None
    duplex: str | None = None
    rx_bytes: int | None = None
    tx_bytes: int | None = None
    rx_packets: int | None = None
    tx_packets: int | None = None
    rx_errors: int | None = None
    tx_errors: int | None = None


@dataclass
class GatewayData:
    """One poll's worth of gateway state."""

    uptime: int
    broadband: BroadbandStats = field(default_factory=BroadbandStats)
