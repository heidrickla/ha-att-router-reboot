"""Local stand-in for the checks CI would run.

hassfest and the HACS action run in CI; this approximates the parts of them
that can be checked with no network at all, plus the cross-file consistency
that nothing else checks: translation keys against icons, exceptions raised
against exceptions declared, actions registered against actions described,
the quality scale against the pinned rule list. Run it before a push so the
push is not the first verification.

    python tools/validate_local.py
"""

from __future__ import annotations

import ast
import ipaddress
import json
import os
import re
import sys
from typing import Any

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DOMAIN = "att_router_reboot"
COMP = os.path.join(ROOT, "custom_components", DOMAIN)
PLATFORMS = ("binary_sensor", "button", "sensor")

# In-repo brand images are served by Home Assistant from this release on; an
# older floor in hacs.json would advertise an install with no icon.
BRAND_FLOOR = (2026, 3, 0)

# Manifest URLs Home Assistant and HACS put in front of the user. A host only
# the author can reach makes both links dead for everyone else.
PUBLIC_URL_KEYS = ("documentation", "issue_tracker")

# hassfest requires these for a custom integration.
REQUIRED_MANIFEST = [
    "domain",
    "name",
    "documentation",
    "codeowners",
    "iot_class",
    "version",
]
VALID_IOT_CLASS = {
    "assumed_state",
    "cloud_polling",
    "cloud_push",
    "local_polling",
    "local_push",
    "calculated",
}

# Exceptions whose message reaches the user: the integration card, the
# action call, the log line. Each must be raised with a translation key.
TRANSLATED_EXCEPTIONS = {
    "HomeAssistantError",
    "ServiceValidationError",
    "ConfigEntryNotReady",
    "ConfigEntryAuthFailed",
    "ConfigEntryError",
    "UpdateFailed",
}

# Pinned from developers.home-assistant.io/docs/core/integration-quality-scale/checklist
# (checked 2026-09-02: 54 rules, none new or deprecated). The list is pinned
# here on purpose: a quality_scale.yaml that is missing a rule reads as
# complete, and checking against the full list turns an omission into a
# failure.
ALL_RULES = {
    # Bronze
    "action-setup",
    "appropriate-polling",
    "brands",
    "common-modules",
    "config-flow-test-coverage",
    "config-flow",
    "dependency-transparency",
    "docs-actions",
    "docs-conditions",
    "docs-high-level-description",
    "docs-installation-instructions",
    "docs-removal-instructions",
    "docs-triggers",
    "entity-event-setup",
    "entity-unique-id",
    "has-entity-name",
    "runtime-data",
    "test-before-configure",
    "test-before-setup",
    "unique-config-entry",
    # Silver
    "action-exceptions",
    "config-entry-unloading",
    "docs-configuration-parameters",
    "docs-installation-parameters",
    "entity-unavailable",
    "integration-owner",
    "log-when-unavailable",
    "parallel-updates",
    "reauthentication-flow",
    "test-coverage",
    # Gold
    "devices",
    "diagnostics",
    "discovery-update-info",
    "discovery",
    "docs-data-update",
    "docs-examples",
    "docs-known-limitations",
    "docs-supported-devices",
    "docs-supported-functions",
    "docs-troubleshooting",
    "docs-use-cases",
    "dynamic-devices",
    "entity-category",
    "entity-device-class",
    "entity-disabled-by-default",
    "entity-translations",
    "exception-translations",
    "icon-translations",
    "reconfiguration-flow",
    "repair-issues",
    "stale-devices",
    # Platinum
    "async-dependency",
    "inject-websession",
    "strict-typing",
}

failures: list[str] = []
notes: list[str] = []


def read(*parts: str) -> str:
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def read_json(*parts: str) -> Any:
    return json.loads(read(*parts))


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def constants(source: str, prefix: str) -> dict[str, str]:
    """Module-level string assignments whose name starts with prefix."""
    found: dict[str, str] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id.startswith(prefix)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            found[target.id] = node.value.value
    return found


def untranslated_raises(source: str, filename: str) -> list[str]:
    """Calls to user-facing exception classes made without a translation key."""
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name not in TRANSLATED_EXCEPTIONS:
            continue
        if not any(kw.arg == "translation_key" for kw in node.keywords):
            out.append(f"{filename}:{node.lineno}: {name}(...) has no translation_key")
    return out


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", text)[:3])


REPO_ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        # The AT&T factory default gateway address: const.DEFAULT_HOST, the
        # config flow strings, the README and the test fixtures all carry it.
        "192.168.1.254",
        # A user-entered host in tests/ha/test_config_flow.py.
        "10.0.0.1",
    }
)

# ------------------------------------------------- development-host refusal
# hassfest and the HACS action read the manifest and nothing else, so a
# development address anywhere in the tree - a workflow comment, a README, a
# docstring - ships with every check green. Two rules, one strict and one
# narrower: the manifest URLs are refused for anything a user cannot open,
# and every published file is refused for anything that names this network.
import subprocess as _subprocess  # noqa: E402
from urllib.parse import urlsplit as _urlsplit  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _netblocks  # noqa: E402

MANIFEST_NETS = tuple(
    ipaddress.ip_network(c)
    for c in _netblocks.TREE_CIDRS + _netblocks.MANIFEST_ONLY_CIDRS
)
TREE_NETS = tuple(ipaddress.ip_network(c) for c in _netblocks.TREE_CIDRS)
MANIFEST_ONLY_NAMES = ("localhost",)
PRIVATE_SUFFIXES = _netblocks.PRIVATE_SUFFIXES

# Hosts that look like a development host and are not one. Every entry is
# load-bearing in this repository and carries the reason on its line; an
# entry added without one is how the rule stops working.
ALLOWED_HOSTS = frozenset(
    {
        # The default Home Assistant address, in every installation document.
        "homeassistant.local",
    }
    | REPO_ALLOWED_HOSTS
)

# Text that ships to whoever clones or installs the repository. The file list
# comes from git rather than a walk: git already knows what is ignored, which
# is how private operational notes under an ignored directory stay out, and
# --others adds a file staged for this commit but not yet added.
# Membership is decided by content, not by extension. A suffix allow-list let
# a Makefile, a Dockerfile, a shell script and a .env.example through unread,
# and a pass computed from files never opened prints the same line as a real
# one. A file is skipped only when its bytes will not decode as text.
# The one published file the scan skips: it holds the CIDRs the scan matches
# on, so it would report itself. Nothing else may live in it.
SCAN_EXEMPT = ("tools/_netblocks.py",)
# Development host names come from the environment, not from a tracked file.
DEV_NAMES_ENV = "ATT_ROUTER_DEV_HOSTNAMES"

IP_LITERAL_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
URL_RE = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s\"'`<>)\]},]+")
# A host written in prose with no scheme. The suffix must end the name:
# \b would match the "home" of home-assistant.io.
BARE_HOST_RE = re.compile(
    r"(?<![\w.-])(?:[a-z0-9][a-z0-9-]*\.)+"
    r"(?:corp|home|home\.arpa|intranet|internal|lan|local|localdomain)(?![\w-])",
    re.IGNORECASE,
)
# A host made of anything else is a template - f"http://{host}/" - not a host.
HOST_CHARS_RE = re.compile(r"^[a-z0-9.\-\[\]:]+$", re.IGNORECASE)


def is_netmask(text: str) -> bool:
    """A dotted quad written as a contiguous subnet mask, 255.255.255.0 and up.

    Every such mask sits in the top reserved block and would otherwise be
    refused as a reserved address. The all-zero mask is a mask too, and is
    deliberately not exempt: as a host it is the unspecified address.
    """
    if not text.startswith("255."):
        return False
    try:
        value = int(ipaddress.IPv4Address(text))
    except ipaddress.AddressValueError:
        return False
    inverted = (~value) & 0xFFFFFFFF
    return inverted & (inverted + 1) == 0


def blocked_address(text: str, nets: tuple[Any, ...]) -> bool:
    """Whether text is an address literal inside one of nets."""
    if is_netmask(text):
        return False
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    return any(address in net for net in nets)


def blocked_host(host: str, nets: tuple[Any, ...], names: tuple[str, ...] = ()) -> bool:
    """Whether a hostname resolves or routes inside one network only.

    `names` are hosts refused by spelling rather than by address family. Only
    the manifest rule passes any: "localhost" names no machine on this
    network, so it is a dead documentation link but not a disclosure.
    """
    host = host.strip().rstrip(".").lower()
    if not host or host in ALLOWED_HOSTS:
        return False
    if host in names:
        return True
    if blocked_address(host, nets):
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        # A literal outside nets is a public address, whatever its shape.
        return False
    if host.endswith(PRIVATE_SUFFIXES):
        return True
    # A name with no dot is resolved against whatever search domain the reader
    # happens to have, so it names a machine on a LAN rather than on the net.
    return "." not in host


def unreachable_host(url: str) -> str | None:
    """The host of a manifest URL no user outside this network can open."""
    if not isinstance(url, str) or not url:
        return None
    try:
        host = _urlsplit(url).hostname or ""
    except ValueError:
        return None
    if host and not HOST_CHARS_RE.match(host):
        return None
    return host if blocked_host(host, MANIFEST_NETS, MANIFEST_ONLY_NAMES) else None


def malformed_url(url: Any) -> bool:
    """A manifest URL that is not an absolute http(s) URL with a host.

    unreachable_host answers a host or None, so a string with no host has
    nothing to report and needs this check instead.
    """
    if not isinstance(url, str) or not url:
        return True
    try:
        parts = _urlsplit(url)
    except ValueError:
        return True
    return parts.scheme not in {"http", "https"} or not parts.hostname


def published_files() -> list[str]:
    """Every file that ships, relative to ROOT, from git's own index.

    Falls back to a walk when git is not there - an extracted tarball - so the
    rule still runs, and says so, rather than passing on an empty list.
    """
    paths: list[str] = []
    try:
        listing = _subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except OSError, _subprocess.SubprocessError:
        listing = None
    if listing is not None and listing.returncode == 0:
        paths = [p for p in listing.stdout.split("\0") if p]
    else:
        notes.append("git not available - the tree scan walked the directory instead")
        for dirpath, dirs, files in os.walk(ROOT):
            dirs[:] = [
                d
                for d in dirs
                if d not in {"__pycache__", "venv", "htmlcov", "node_modules"}
                and not (d.startswith(".") and d not in {".gitea", ".github"})
            ]
            for f in files:
                paths.append(
                    os.path.relpath(os.path.join(dirpath, f), ROOT).replace("\\", "/")
                )
    return sorted(p for p in paths if p not in SCAN_EXEMPT)


def tree_hits(text: str, name_re: Any = None) -> list[tuple[int, str]]:
    """Every development host named in text, as (line number, host)."""
    hits: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if name_re is not None:
            for name in name_re.findall(line):
                if name.lower() not in ALLOWED_HOSTS:
                    hits.append((number, name.lower()))
        for literal in IP_LITERAL_RE.findall(line):
            if literal not in ALLOWED_HOSTS and blocked_address(literal, TREE_NETS):
                hits.append((number, literal))
        for url in URL_RE.findall(line):
            try:
                host = _urlsplit(url).hostname or ""
            except ValueError:
                continue
            if not host or not HOST_CHARS_RE.match(host):
                continue
            if blocked_host(host, TREE_NETS):
                hits.append((number, host))
        for name in BARE_HOST_RE.findall(line):
            if name.lower() not in ALLOWED_HOSTS:
                hits.append((number, name.lower()))
    return hits


def internal_names() -> list[str]:
    """Development host names the tree scan refuses, read from outside the tree.

    Naming them in a published file is the disclosure this rule exists to
    prevent, so they come from the environment: ATT_ROUTER_DEV_HOSTNAMES holds
    them comma-separated, or holds a path to a file with one per line. A name
    matches as the prefix of a longer word, so a bare name also catches the
    same name carrying a digit or a -ci suffix. No example host is spelled out
    here: a real name in this file is the disclosure, and a fictional one
    misfires the day someone runs a machine by that name.
    """
    raw = os.environ.get(DEV_NAMES_ENV, "").strip()
    if not raw:
        return []
    if os.path.isfile(raw):
        raw = read(raw).replace("\n", ",")
    return [n.strip().lower() for n in raw.split(",") if n.strip()]


def scan_controls(names: list[str], name_re: Any) -> None:
    """Fire both matchers on synthetic input before a clean tree is believed.

    A tree holding nothing and a matcher that matches nothing print the same
    result. The control lines are built here and never written to a file.
    """
    net = next(n for n in TREE_NETS if n.version == 4)
    address = next(
        str(net.network_address + offset)
        for offset in range(1, 16)
        if str(net.network_address + offset) not in ALLOWED_HOSTS
    )
    check(
        tree_hits(f"control line naming {address}") != [],
        f"the tree scan did not match {address}, an address it refuses, so a "
        "clean scan says nothing about the addresses in the tree",
    )
    if not names:
        return
    check(
        tree_hits(f"control line naming {names[0]}-ci", name_re) != [],
        f"the tree scan did not match {names[0]}, a name it was given, so a "
        "clean scan says nothing about the names in the tree",
    )


def scan_published_tree() -> None:
    """Refuse a development host anywhere in the published tree."""
    exempt = os.path.join(ROOT, *SCAN_EXEMPT[0].split("/"))
    if os.path.isfile(exempt):
        allowed_names = {"TREE_CIDRS", "MANIFEST_ONLY_CIDRS", "PRIVATE_SUFFIXES"}
        for node in ast.parse(read(exempt)).body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            targets = node.targets if isinstance(node, ast.Assign) else []
            if not all(
                isinstance(t, ast.Name) and t.id in allowed_names for t in targets
            ):
                failures.append(
                    f"{SCAN_EXEMPT[0]} holds more than the pinned address space; "
                    "the tree scan skips this file, so nothing else may live in it"
                )
                break
    names = internal_names()
    name_re = None
    if names:
        name_re = re.compile(
            r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\w*",
            re.IGNORECASE,
        )
        notes.append(f"{len(names)} development host names given to the tree scan")
    else:
        notes.append(
            "no development host names given to the tree scan, so its name half "
            "did not run and this result covers addresses and URLs only; set "
            f"{DEV_NAMES_ENV} to run the name half"
        )
    scan_controls(names, name_re)
    seen = 0
    for path in published_files():
        full = os.path.join(ROOT, *path.split("/"))
        if not os.path.isfile(full):
            continue
        try:
            text = read(full)
        except OSError, UnicodeDecodeError:
            continue
        if "\0" in text:
            continue
        seen += 1
        for number, host in tree_hits(text, name_re):
            failures.append(
                f"{path}:{number} names {host} - that host is on the development "
                "network and means nothing to a user who installs this"
            )
    check(seen > 0, "the published-tree scan read no files, so it proved nothing")


def main() -> int:
    manifest = read_json(COMP, "manifest.json")
    const_src = read(COMP, "const.py")
    strings = read_json(COMP, "strings.json")

    # ---------------------------------------------------------- manifest
    for key in REQUIRED_MANIFEST:
        check(key in manifest, f"manifest.json missing required key {key!r}")
    check(
        manifest.get("domain") == DOMAIN,
        f"manifest domain is {manifest.get('domain')!r}",
    )
    check(
        manifest.get("iot_class") in VALID_IOT_CLASS,
        f"manifest iot_class {manifest.get('iot_class')!r} is not a valid value",
    )
    check(
        isinstance(manifest.get("codeowners"), list)
        and all(c.startswith("@") for c in manifest["codeowners"]),
        "manifest codeowners entries must start with @",
    )
    keys = list(manifest)
    check(
        keys[:2] == ["domain", "name"] and keys[2:] == sorted(keys[2:]),
        "manifest keys must be domain, name, then alphabetical (hassfest MANIFEST)",
    )
    for url_key in PUBLIC_URL_KEYS:
        url = manifest.get(url_key)
        if not url:
            continue
        host = unreachable_host(url)
        check(
            host is None,
            f"manifest {url_key} host {host!r} is not reachable from outside "
            "this network - the link is dead for every other user",
        )
    check(
        "quality_scale" not in manifest,
        "quality_scale in manifest.json: the badge is core-only, a custom "
        "integration builds to the rules and does not claim a tier",
    )

    const_version = constants(const_src, "VERSION").get("VERSION")
    check(
        const_version == manifest.get("version"),
        f"const.VERSION {const_version!r} != manifest version "
        f"{manifest.get('version')!r} - HA reports one and HACS the other",
    )
    # Three files carry the version. HA reads the manifest, HACS reads the
    # release, const.VERSION reaches diagnostics and pyproject names the repo.
    pyproject = read(ROOT, "pyproject.toml")
    m = re.search(
        r'^\[project\][^\[]*?^version\s*=\s*"([^"]+)"', pyproject, re.M | re.S
    )
    check(m is not None, "pyproject.toml has no [project] version to cross-check")
    if m:
        check(
            m.group(1) == manifest.get("version"),
            f"pyproject version {m.group(1)!r} != manifest {manifest.get('version')!r}",
        )

    # ---------------------------------------------------------- hacs.json
    hacs = read_json(ROOT, "hacs.json")
    check("name" in hacs, "hacs.json must contain name")
    # hacs.xyz/docs/publish/include: a repository for a single or limited set
    # of countries must set country in the released hacs.json. The hacs/action
    # does not check it; a reviewer does.
    check(
        "country" in hacs,
        "hacs.json must contain country - this integration works only against "
        "an AT&T gateway, which is sold only in the United States",
    )

    # ---------------------------------------------------------- brand images
    brand = os.path.join(COMP, "brand")
    for name in ("icon.png", "icon@2x.png", "logo.png", "logo@2x.png"):
        check(os.path.isfile(os.path.join(brand, name)), f"missing brand/{name}")
    if os.path.isdir(brand):
        check(
            version_tuple(hacs.get("homeassistant", "0")) >= BRAND_FLOOR,
            f"hacs.json homeassistant {hacs.get('homeassistant')!r} is below "
            f"{'.'.join(map(str, BRAND_FLOOR))}, the first release that serves "
            "in-repo brand images",
        )
        try:
            from PIL import Image

            for name, want in (("icon.png", 256), ("icon@2x.png", 512)):
                path = os.path.join(brand, name)
                if os.path.isfile(path):
                    with Image.open(path) as im:
                        check(
                            im.size == (want, want),
                            f"brand/{name} is {im.size}, must be {want}x{want}",
                        )
            for name, lo, hi in (("logo.png", 128, 256), ("logo@2x.png", 256, 512)):
                path = os.path.join(brand, name)
                if os.path.isfile(path):
                    with Image.open(path) as im:
                        short = min(im.size)
                        check(
                            lo <= short <= hi,
                            f"brand/{name} shortest side {short} not in {lo}-{hi}",
                        )
        except ImportError:
            notes.append("Pillow not installed - brand image sizes not checked")

    # ---------------------------------------------------------- translations
    en = read_json(COMP, "translations", "en.json")
    check(
        strings == en,
        "strings.json and translations/en.json differ - copy strings.json over",
    )

    # ---------------------------------------------------------- actions
    services_yaml = os.path.join(COMP, "services.yaml")
    check(os.path.isfile(services_yaml), "services.yaml is missing")
    service_consts = set(constants(const_src, "SERVICE_").values())
    declared_services = set(strings.get("services", {}))
    check(
        declared_services == service_consts,
        f"strings.json describes {sorted(declared_services)} but const.py "
        f"registers {sorted(service_consts)}",
    )
    try:
        import yaml

        services = yaml.safe_load(read(services_yaml)) or {}
        check(
            set(services) == service_consts,
            f"services.yaml declares {sorted(services)} but const.py registers "
            f"{sorted(service_consts)}",
        )
        for name, spec in services.items():
            yaml_fields = set((spec or {}).get("fields", {}))
            described = set(strings.get("services", {}).get(name, {}).get("fields", {}))
            check(
                yaml_fields == described,
                f"action {name}: services.yaml fields {sorted(yaml_fields)} != "
                f"strings.json fields {sorted(described)}",
            )
            for field_spec in (spec or {}).get("fields", {}).values():
                selector = (field_spec or {}).get("selector", {})
                tkey = (selector.get("select") or {}).get("translation_key")
                if tkey:
                    check(
                        tkey in strings.get("selector", {}),
                        f"selector translation {tkey!r} missing from strings.json",
                    )
    except ImportError:
        notes.append("PyYAML not installed - services.yaml not parsed")

    # ---------------------------------------------------------- quality scale
    scale_path = os.path.join(COMP, "quality_scale.yaml")
    check(os.path.isfile(scale_path), "quality_scale.yaml is missing")
    if os.path.isfile(scale_path):
        try:
            import yaml

            declared = yaml.safe_load(read(scale_path)).get("rules", {})
            missing = ALL_RULES - set(declared)
            check(not missing, f"quality_scale.yaml does not mention {sorted(missing)}")
            unknown = set(declared) - ALL_RULES
            check(not unknown, f"quality_scale.yaml invents rules {sorted(unknown)}")
            for rule, value in sorted(declared.items()):
                if isinstance(value, dict):
                    check(
                        value.get("status") in {"done", "todo", "exempt"},
                        f"{rule}: status must be done/todo/exempt",
                    )
                    if value.get("status") != "done":
                        check(
                            bool(str(value.get("comment", "")).strip()),
                            f"{rule}: a non-done status needs a comment saying why",
                        )
                else:
                    check(value == "done", f"{rule}: bare value must be 'done'")
            todo = sorted(
                r
                for r, v in declared.items()
                if isinstance(v, dict) and v.get("status") == "todo"
            )
            if todo:
                notes.append(f"quality scale still todo: {', '.join(todo)}")

            # A `done` has to be contradicted by the file set when the code
            # for it is absent. Prose in a comment is not evidence; these are
            # the mechanisms whose presence can be read off the repository.
            def status(rule: str) -> str:
                value = declared.get(rule)
                if isinstance(value, dict):
                    return str(value.get("status"))
                return "done" if value == "done" else "missing"

            component_src = "\n".join(
                read(COMP, f) for f in sorted(os.listdir(COMP)) if f.endswith(".py")
            )
            github_workflow = os.path.join(ROOT, ".github", "workflows", "tests.yml")
            ci = read(github_workflow) if os.path.isfile(github_workflow) else ""
            for rule, present, missing_because in (
                (
                    "test-coverage",
                    "--cov-fail-under=95" in ci,
                    "no --cov-fail-under=95 in .github/workflows/tests.yml, so "
                    "nothing stops coverage falling below 95%",
                ),
                (
                    "strict-typing",
                    "strict = true" in pyproject and "mypy " in ci,
                    "pyproject does not set mypy strict, or the GitHub workflow "
                    "does not run mypy",
                ),
                (
                    "repair-issues",
                    "async_create_issue" in component_src,
                    "no async_create_issue call anywhere in the integration",
                ),
                (
                    "reconfiguration-flow",
                    "async_step_reconfigure" in component_src,
                    "no async_step_reconfigure in the config flow",
                ),
                (
                    "reauthentication-flow",
                    "async_step_reauth" in component_src,
                    "no async_step_reauth in the config flow",
                ),
                (
                    "diagnostics",
                    os.path.isfile(os.path.join(COMP, "diagnostics.py")),
                    "no diagnostics.py",
                ),
                (
                    "discovery",
                    any(
                        k in manifest
                        for k in (
                            "bluetooth",
                            "dhcp",
                            "homekit",
                            "mqtt",
                            "ssdp",
                            "usb",
                            "zeroconf",
                        )
                    ),
                    "the manifest declares no discovery method",
                ),
            ):
                if status(rule) == "done":
                    check(present, f"{rule} is done but {missing_because}")
        except ImportError:
            notes.append("PyYAML not installed - quality_scale.yaml not parsed")

    # ------------------------------------------------------ icon translations
    # Every translation key an entity uses needs a name, and every name needs
    # an entity using it. Icons are optional - a device class supplies one -
    # but an icon for a key no entity uses is drift. Both forms are matched:
    # the class attribute and the EntityDescription keyword.
    icons = read_json(COMP, "icons.json")
    key_re = re.compile(r'(?:_attr_translation_key\s*=|\btranslation_key=)\s*"([^"]+)"')
    # An exception is raised with translation_domain=DOMAIN right before its
    # key; entity and issue keys never carry translation_domain. Subtracted
    # here so an error raised inside a platform file is not read as one of
    # that platform's entities.
    exc_re = re.compile(r'translation_domain=DOMAIN,\s*translation_key="([^"]+)"')
    for platform in PLATFORMS:
        source = read(COMP, f"{platform}.py")
        used = set(key_re.findall(source)) - set(exc_re.findall(source))
        declared_icons = set(icons.get("entity", {}).get(platform, {}))
        named = set(strings.get("entity", {}).get(platform, {}))
        check(
            declared_icons <= used,
            f"{platform}: icons for {sorted(declared_icons - used)} have no entity",
        )
        check(used == named, f"{platform}: names {sorted(named ^ used)} out of step")
    service_icons = set(icons.get("services", {}))
    check(
        service_icons == service_consts,
        f"icons.json services {sorted(service_icons)} != {sorted(service_consts)}",
    )

    # ------------------------------------------------- exception translations
    raised: set[str] = set()
    for f in sorted(os.listdir(COMP)):
        if f.endswith(".py"):
            source = read(COMP, f)
            raised |= set(exc_re.findall(source))
            failures.extend(untranslated_raises(source, f))
    declared_exc = set(strings.get("exceptions", {}))
    check(
        raised <= declared_exc,
        f"code raises undeclared exception keys {sorted(raised - declared_exc)}",
    )
    check(
        declared_exc <= raised,
        f"strings.json declares unused exceptions {sorted(declared_exc - raised)}",
    )

    # ----------------------------------------------------- issue translations
    issue_consts = set(constants(const_src, "ISSUE_").values())
    declared_issues = set(strings.get("issues", {}))
    check(
        issue_consts == declared_issues,
        f"const.py issues {sorted(issue_consts)} != strings.json issues "
        f"{sorted(declared_issues)}",
    )

    # ------------------------------------------------------------ platforms
    init_src = read(COMP, "__init__.py")
    for platform in PLATFORMS:
        check(
            f"Platform.{platform.upper()}" in init_src,
            f"{platform}.py exists but Platform.{platform.upper()} is not forwarded",
        )
        check(
            "PARALLEL_UPDATES" in read(COMP, f"{platform}.py"),
            f"{platform}.py does not set PARALLEL_UPDATES",
        )
    # hassfest: an integration with async_setup must say how it is configured.
    if "def async_setup(" in init_src:
        check(
            "CONFIG_SCHEMA" in init_src,
            "__init__.py defines async_setup without a CONFIG_SCHEMA",
        )

    # ---------------------------------------------- development-host refusal
    for _key in ("documentation", "issue_tracker"):
        if _key in manifest:
            check(
                not malformed_url(manifest.get(_key)),
                f"manifest {_key} is not an absolute http(s) URL a user can open",
            )
    scan_published_tree()

    # ---------------------------------------------------------- syntax
    for dirpath, _dirs, files in os.walk(COMP):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(dirpath, f)
                try:
                    ast.parse(read(path))
                except SyntaxError as err:
                    failures.append(f"{f}: {err}")

    # ---------------------------------------------------------- report
    print(f"manifest {manifest.get('domain')} {manifest.get('version')}")
    for n in notes:
        print(f"  NOTE   {n}")
    for f in failures:
        print(f"  FAIL   {f}")
    if not failures:
        print("  all offline checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
