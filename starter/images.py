"""Opt-in check that the pinned container images are still current.

This is the only part of the starter that uses the network, and only when
``bootstrap.py --check-images`` is requested. It lists the tags of each
image through the standard registry API and compares the newest release
with the version pinned in ``starter.versions``.
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import Message


DOCKER_HUB: str = "registry-1.docker.io"
TIMEOUT: float = 60.0
CHALLENGE: re.Pattern[str] = re.compile(r'(\w+)="([^"]*)"')
NEXT_PAGE: re.Pattern[str] = re.compile(r"<([^>]+)>")


@dataclass(frozen=True, slots=True)
class Pin:
    """One pinned image tag and the pattern of the tags it competes with."""

    label: str
    registry: str
    repository: str
    pattern: str
    pinned: str


def pins() -> tuple[Pin, ...]:
    """Built-in image tags; custom images have no inferred update policy."""
    return (
        Pin("Debian", DOCKER_HUB, "library/debian", r"(\d+)", "13"),
        Pin("Ubuntu LTS", DOCKER_HUB, "library/ubuntu", r"(\d[02468])\.04", "26.04"),
    )


def fetch(url: str, token: str) -> tuple[bytes, Message]:
    """GET one HTTPS URL, optionally with a bearer token."""
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-HTTPS URL {url}")
    request: urllib.request.Request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read(), response.headers


def anonymous_token(challenge: str) -> str:
    """Obtain a pull token as described by a registry's 401 challenge."""
    fields: dict[str, str] = dict(CHALLENGE.findall(challenge))
    query: str = "&".join(
        f"{key}={fields[key]}" for key in ("service", "scope") if key in fields
    )
    body, _headers = fetch(f"{fields['realm']}?{query}", "")
    document: object = json.loads(body)
    if not isinstance(document, dict):
        raise TypeError("registry returned an invalid token document")
    return str(document.get("token") or document.get("access_token"))


def list_tags(registry: str, repository: str) -> list[str]:
    """Return all tags of a repository, following pagination."""
    url: str = f"https://{registry}/v2/{repository}/tags/list?n=10000"
    token: str = ""
    tags: list[str] = []
    while url:
        try:
            body, headers = fetch(url, token)
        except urllib.error.HTTPError as error:
            challenge: str = error.headers.get("WWW-Authenticate", "")
            if error.code != 401 or token or not challenge:
                raise
            token = anonymous_token(challenge)
            continue
        document: object = json.loads(body)
        if not isinstance(document, dict):
            raise TypeError("registry returned an invalid tag list")
        page: object = document.get("tags")
        if isinstance(page, list):
            tags.extend(str(tag) for tag in page)
        following: re.Match[str] | None = NEXT_PAGE.search(
            headers.get("Link", "")
        )
        url = f"https://{registry}{following.group(1)}" if following else ""
    return tags


def newest(pattern: str, tags: list[str]) -> str:
    """Return the matching tag with the highest numeric version."""
    compiled: re.Pattern[str] = re.compile(pattern)
    matching: list[tuple[tuple[int, ...], str]] = []
    for tag in tags:
        match: re.Match[str] | None = compiled.fullmatch(tag)
        if match is not None:
            matching.append((tuple(map(int, match.groups())), tag))
    if not matching:
        raise ValueError(f"no tag matches {pattern}")
    return max(matching)[1]


def check() -> int:
    """Print the state of every pinned image; return 1 if any is stale."""
    cache: dict[tuple[str, str], list[str]] = {}
    stale: bool = False
    for pin in pins():
        source: tuple[str, str] = (pin.registry, pin.repository)
        if source not in cache:
            cache[source] = list_tags(*source)
        latest: str = newest(pin.pattern, cache[source])
        current: bool = latest == pin.pinned
        stale = stale or not current
        verdict: str = "ok      " if current else "OUTDATED"
        print(
            f"{verdict} {pin.label:20} pinned {pin.pinned:32} newest {latest}"
        )
    if stale:
        print("Update image pins in starter/images.py and starter/payload/schema.py, then re-run the tests.")
    return int(stale)
