"""Driver updates must never silently create another Android sandbox."""

import importlib.util
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "android/scripts/deploy_consumer_to_device.py"
SPEC = importlib.util.spec_from_file_location("android_install_identity", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
DRIVER = MODULE.CONSUMER_ID


def badging(package=DRIVER + ".debug"):
    return f"package: name='{package}' versionCode='10085' versionName='1.5-debug'\n"


@pytest.mark.parametrize("driver", [DRIVER, DRIVER + ".debug"])
def test_actual_apk_driver_metadata_is_accepted(driver):
    assert MODULE.apk_metadata(badging(driver))["name"] == driver


@pytest.mark.parametrize("package", [DRIVER + ".testhost", DRIVER + ".debug.test", "com.example.other"])
def test_test_and_unrelated_apks_are_rejected(package):
    with pytest.raises(ValueError, match="normal release/debug"):
        MODULE.apk_metadata(badging(package))


@pytest.mark.parametrize("payload", ["", "package: name='de.youspeed.android'", badging() + badging(),
                                    "package: name='de.youspeed.android' versionCode='0' versionName='1.5'"])
def test_unreadable_or_ambiguous_apk_metadata_fails_closed(payload):
    with pytest.raises(ValueError, match="metadata"):
        MODULE.apk_metadata(payload)


@pytest.mark.parametrize("payload", ["", "error: device offline", "package:de.youspeed.android\nError: denied",
                                    "package:/data/app/example.apk=de.youspeed.android"])
def test_unreadable_package_inventory_fails_closed(payload):
    with pytest.raises(ValueError, match="inventory"):
        MODULE.installed_packages(payload)


def test_hidden_instrumentation_is_excluded_but_separate_driver_hosts_block():
    packages = MODULE.installed_packages(
        "package:android\npackage:de.youspeed.android.debug\n"
        "package:de.youspeed.android.debug.test\npackage:de.youspeed.android.testhost.test\n")
    MODULE.validate_identity(packages, DRIVER + ".debug")
    for conflict in [DRIVER, DRIVER + ".testhost", DRIVER + ".other.test"]:
        with pytest.raises(ValueError, match="Preserve and consolidate"):
            MODULE.validate_identity(packages | {conflict}, DRIVER + ".debug")


@pytest.fixture
def deployment(tmp_path):
    sdk = tmp_path / "sdk"
    for relative in ["platform-tools/adb", "build-tools/35.0.0/aapt2", "build-tools/36.0.0/aapt2"]:
        tool = sdk / relative
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.touch()
        tool.chmod(0o755)
    apk = tmp_path / "app with spaces.apk"
    apk.touch()
    return apk, sdk


def fake_runner(outputs):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        result = outputs[len(calls) - 1]
        if isinstance(result, Exception):
            raise result
        return CompletedProcess(argv, 0, stdout=result, stderr="")

    return calls, run


def test_update_uses_actual_package_explicit_device_and_only_install_replace(deployment):
    apk, sdk = deployment
    calls, run = fake_runner([badging(), "package:android\npackage:de.youspeed.android.debug\n", "Success\n"])
    metadata = MODULE.deploy(apk, "test-serial", sdk, run=run)
    assert metadata["name"] == DRIVER + ".debug"
    assert calls[0][0] == [str(sdk / "build-tools/36.0.0/aapt2"), "dump", "badging", str(apk.resolve())]
    assert calls[1][0] == [str(sdk / "platform-tools/adb"), "-s", "test-serial", "shell", "pm", "list", "packages"]
    assert calls[2][0] == [str(sdk / "platform-tools/adb"), "-s", "test-serial", "install", "-r", str(apk.resolve())]
    assert all(kwargs["check"] and kwargs["capture_output"] and kwargs["text"] for _, kwargs in calls)
    assert len(calls) == 3  # Installation does not implicitly launch or clear data.


@pytest.mark.parametrize("inventory", ["package:de.youspeed.android.testhost\n", "device offline\n", ""])
def test_conflicting_or_unreadable_inventory_never_reaches_install(deployment, inventory):
    apk, sdk = deployment
    calls, run = fake_runner([badging(), inventory])
    with pytest.raises(ValueError):
        MODULE.deploy(apk, "test-serial", sdk, run=run)
    assert len(calls) == 2


def test_failed_metadata_command_never_contacts_device(deployment):
    apk, sdk = deployment
    calls, run = fake_runner([CalledProcessError(1, ["aapt2"])])
    with pytest.raises(CalledProcessError):
        MODULE.deploy(apk, "test-serial", sdk, run=run)
    assert len(calls) == 1


def test_launch_is_explicit_and_uses_the_verified_apk_package(deployment):
    apk, sdk = deployment
    calls, run = fake_runner([badging(DRIVER), "package:android\n", "Success\n", "Starting: Intent\n"])
    MODULE.deploy(apk, "test-serial", sdk, launch=True, run=run)
    assert calls[-1][0][-5:] == ["shell", "am", "start", "-n", DRIVER + "/de.youspeed.android.alpha.MainActivity"]


def test_missing_sdk_tools_fail_before_any_command(deployment):
    apk, sdk = deployment
    (sdk / "platform-tools/adb").unlink()
    calls, run = fake_runner([])
    with pytest.raises(ValueError, match="SDK adb and aapt2"):
        MODULE.deploy(apk, "test-serial", sdk, run=run)
    assert not calls
