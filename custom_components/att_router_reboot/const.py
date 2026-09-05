"""Constants for the AT&T Router Reboot integration."""

from datetime import timedelta

DOMAIN = "att_router_reboot"
MANUFACTURER = "AT&T"
# Kept equal to manifest.json's version; tools/validate_local.py checks.
VERSION = "0.2.0"

CONF_ACCESS_CODE = "access_code"
CONF_VERIFY_SSL = "verify_ssl"

# The gateway ships a self-signed certificate on its LAN address, so TLS
# verification is off by default. A user who has installed their own cert can
# turn it on.
DEFAULT_HOST = "192.168.1.254"
DEFAULT_VERIFY_SSL = False

# Uptime is read from sysinfo.ha, which needs no login and changes only slowly.
# Two minutes is frequent enough to notice a reboot and gentle on an embedded
# web server that is doing real routing work.
SCAN_INTERVAL = timedelta(minutes=2)

# Options: an optional built-in schedule, for users who would rather not wire
# up an automation. "off" leaves rebooting entirely to the button and action.
CONF_SCHEDULE = "schedule"
CONF_SCHEDULE_TIME = "schedule_time"
CONF_SCHEDULE_WEEKDAY = "schedule_weekday"

SCHEDULE_OFF = "off"
SCHEDULE_DAILY = "daily"
SCHEDULE_WEEKLY = "weekly"
SCHEDULES = [SCHEDULE_OFF, SCHEDULE_DAILY, SCHEDULE_WEEKLY]

WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

DEFAULT_SCHEDULE = SCHEDULE_OFF
DEFAULT_SCHEDULE_TIME = "04:00:00"
DEFAULT_SCHEDULE_WEEKDAY = "sunday"

# A scheduled reboot is skipped when the gateway has been up for less than this,
# so a restart loop (or a schedule firing minutes after a manual reboot) cannot
# keep power-cycling the one device the whole house depends on for internet.
MIN_UPTIME_FOR_SCHEDULED_REBOOT = timedelta(minutes=30)

SERVICE_REBOOT = "reboot"

# A scheduled reboot fires with nobody watching it. A rejected code starts the
# reauth flow, which is its own prompt; any other failure is raised as a repair
# issue so it is more than a log line.
ISSUE_SCHEDULED_REBOOT_FAILED = "scheduled_reboot_failed"
