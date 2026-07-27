"""Guards against shipping GitHub Actions pinned to deprecated Node.js runtimes.

The daily-digest workflow was silently downgraded when actions/cache@v4 and
actions/upload-artifact@v4 (Node.js 20) were deprecated. These tests parse the
real workflow YAML and assert every action we depend on is pinned to at least
the first major version that runs on a supported Node.js runtime, so a stale
pin fails CI instead of only printing a deprecation warning at runtime.
"""

import re
from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "daily-digest.yml"
)

# First major version of each action that runs on Node.js 24 (i.e. not the
# deprecated Node.js 20 runtime). Bump these as GitHub deprecates further.
MIN_MAJOR = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/cache": 5,
    "actions/upload-artifact": 5,
}


def _collect_uses(node):
    """Yield every `uses:` value anywhere in the parsed workflow tree."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses" and isinstance(value, str):
                yield value
            else:
                yield from _collect_uses(value)
    elif isinstance(node, list):
        for item in node:
            yield from _collect_uses(item)


def _base_and_major(uses):
    """('actions/cache/restore@v4') -> ('actions/cache', 4)."""
    ref, _, version = uses.partition("@")
    base = "/".join(ref.split("/")[:2])
    match = re.match(r"v?(\d+)", version)
    major = int(match.group(1)) if match else None
    return base, major


def _load_uses():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return list(_collect_uses(workflow))


def test_workflow_file_exists():
    assert WORKFLOW.is_file(), f"workflow not found at {WORKFLOW}"


def test_all_actions_are_version_pinned():
    for uses in _load_uses():
        _, _, version = uses.partition("@")
        assert version, f"action is not version-pinned: {uses}"


def test_known_actions_meet_min_major_version():
    """Every known action must be at or above its Node.js-24 minimum major."""
    for uses in _load_uses():
        base, major = _base_and_major(uses)
        if base in MIN_MAJOR:
            assert major is not None, f"cannot parse major version from {uses}"
            assert major >= MIN_MAJOR[base], (
                f"{uses} uses major v{major}, but v{MIN_MAJOR[base]}+ is required "
                f"to run on a supported Node.js runtime"
            )


def test_no_deprecated_node20_action_pins():
    """Explicitly reject the exact pins that triggered the CI deprecation."""
    deprecated = {
        "actions/cache/restore@v4",
        "actions/cache/save@v4",
        "actions/cache@v4",
        "actions/upload-artifact@v4",
        "actions/checkout@v4",
        "actions/setup-python@v5",
    }
    found = set(_load_uses()) & deprecated
    assert not found, f"deprecated Node.js 20 action pins present: {sorted(found)}"
