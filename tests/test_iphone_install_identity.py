"""Protect driver containers when deploying builds with different identifiers."""

import importlib.util
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "scripts/iphone/check_consumer_install_identity.py"
SPEC = importlib.util.spec_from_file_location("install_identity", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
DRIVER = MODULE.CONSUMER_ID


def inventory(*identifiers):
    return {"result": {"apps": [{"bundleIdentifier": value} for value in identifiers]}}


@pytest.mark.parametrize("driver", [DRIVER, DRIVER + ".TestHost"])
def test_new_phone_or_same_identity_can_be_installed(driver):
    MODULE.validate_identity(inventory(), driver)
    MODULE.validate_identity(inventory(driver, "com.example.other"), driver)


@pytest.mark.parametrize(
    "installed,target",
    [(DRIVER, DRIVER + ".TestHost"), (DRIVER + ".TestHost", DRIVER)],
)
def test_other_driver_identity_is_never_silently_duplicated(installed, target):
    with pytest.raises(ValueError, match="Preserve and consolidate"):
        MODULE.validate_identity(inventory(installed), target)
    with pytest.raises(ValueError, match="Preserve and consolidate"):
        MODULE.validate_identity(inventory(installed, target), target)


def test_test_host_is_not_a_driver_deployment():
    with pytest.raises(ValueError, match="isolated test host"):
        MODULE.validate_identity(inventory(), DRIVER + ".UnitTests")


@pytest.mark.parametrize("host", [DRIVER + ".UnitTests", "de.youspeed.PackedRuntimeIntegrationTestHost"])
def test_visible_isolated_consumer_hosts_must_be_preserved_and_consolidated(host):
    with pytest.raises(ValueError, match="Preserve and consolidate"):
        MODULE.validate_identity(inventory(DRIVER + ".TestHost", host), DRIVER + ".TestHost")


@pytest.mark.parametrize("payload", [{}, {"result": {}}, {"result": {"apps": [{}]}}])
def test_unreadable_inventory_stops_before_install(payload):
    with pytest.raises(ValueError, match="Cannot verify"):
        MODULE.validate_identity(payload, DRIVER)
