import subprocess
from pathlib import Path

import httpx
from dotenv import dotenv_values

from nova.config import Settings
from nova.core.prompt import compose_system_prompt
from nova.device.location import Location, LocationDetector, location_context, parse_coordinates
from nova.interfaces.setup import run_setup

CHAMBERY_ADDRESS = {"town": "Chambéry", "county": "Savoie", "state": "Auvergne-Rhône-Alpes", "country": "France"}


def powershell_returning(stdout: str | None):
    def run(command, **kwargs):
        if stdout is None:
            raise FileNotFoundError("powershell.exe")
        return subprocess.CompletedProcess(command, 0, stdout, "")

    return run


def fake_web(ip_loc: str = "48.1111,-1.6743", search_results: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/reverse":
            return httpx.Response(200, json={"address": CHAMBERY_ADDRESS})
        if request.url.path == "/search":
            return httpx.Response(200, json=search_results or [])
        return httpx.Response(200, json={"city": "Rennes", "region": "Brittany", "country": "FR", "loc": ip_loc})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_windows_location_is_preferred():
    detector = LocationDetector(powershell_returning("45.581215,5.910249\r\n"), fake_web())
    location = detector.detect()
    assert (location.city, location.region, location.source) == ("Chambéry", "Savoie", "windows")
    assert location.latitude == 45.581215


def test_falls_back_to_ip_when_windows_permission_denied():
    location = LocationDetector(powershell_returning("DENIED\r\n"), fake_web()).detect()
    assert (location.city, location.source) == ("Rennes", "ip")


def test_falls_back_to_ip_when_powershell_is_missing():
    assert LocationDetector(powershell_returning(None), fake_web()).detect().source == "ip"


def test_returns_none_when_everything_fails():
    assert LocationDetector(powershell_returning("UNKNOWN"), fake_web(ip_loc="")).detect() is None


def test_geocode_place_name():
    results = [{"lat": "45.5646", "lon": "5.9178", "address": CHAMBERY_ADDRESS}]
    location = LocationDetector(powershell_returning(None), fake_web(search_results=results)).geocode("Chambéry")
    assert (location.city, location.source) == ("Chambéry", "manual")


def test_parse_coordinates_rejects_garbage():
    assert parse_coordinates("45.5,5.9") == (45.5, 5.9)
    assert parse_coordinates("DENIED") is None
    assert parse_coordinates("999,5") is None


def answers(*replies):
    queue = list(replies)
    return lambda question: queue.pop(0)


def test_setup_saves_confirmed_location_to_env(tmp_path: Path):
    env_path = tmp_path / ".env"
    example = tmp_path / ".env.example"
    example.write_text("NOVA_PROVIDER=claude_code\n")
    detector = LocationDetector(powershell_returning("45.581215,5.910249"), fake_web())

    run_setup(env_path, example, detector, ask=answers("o"))

    values = dotenv_values(env_path)
    assert values["NOVA_PROVIDER"] == "claude_code"
    assert values["NOVA_LOCATION_CITY"] == "Chambéry"
    assert values["NOVA_LOCATION_LATITUDE"] == "45.581215"
    location = Settings(_env_file=env_path).location()
    assert location.city == "Chambéry" and location.longitude == 5.910249


def test_setup_lets_user_correct_a_wrong_location(tmp_path: Path):
    env_path = tmp_path / ".env"
    results = [{"lat": "45.5646", "lon": "5.9178", "address": CHAMBERY_ADDRESS}]
    detector = LocationDetector(powershell_returning("DENIED"), fake_web(search_results=results))

    location = run_setup(env_path, tmp_path / "missing", detector, ask=answers("n", "Chambéry"))

    assert location.source == "manual"
    assert dotenv_values(env_path)["NOVA_LOCATION_CITY"] == "Chambéry"


def test_setup_can_be_skipped(tmp_path: Path):
    env_path = tmp_path / ".env"
    detector = LocationDetector(powershell_returning(None), fake_web(ip_loc=""))
    assert run_setup(env_path, tmp_path / "missing", detector, ask=answers("")) is None
    assert not env_path.exists()


def test_unset_location_in_settings():
    assert Settings(_env_file=None).location() is None


def test_location_is_added_to_system_prompt():
    location = Location("Chambéry", "Savoie", "France", 45.5812, 5.9102, "windows")
    prompt = compose_system_prompt("You are NOVA.", [location_context(location)])
    assert prompt.startswith("You are NOVA.")
    assert "Chambéry, Savoie, France" in prompt and "wttr.in/45.5812,5.9102" in prompt


def test_prompt_unchanged_without_context():
    assert compose_system_prompt("You are NOVA.", []) == "You are NOVA."


def test_powershell_does_not_consume_terminal_input():
    received = {}

    def run(command, **kwargs):
        received.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "DENIED", "")

    LocationDetector(run, fake_web()).windows_coordinates()
    assert received["stdin"] is subprocess.DEVNULL


def test_setup_end_of_input_accepts_detected_location(tmp_path: Path):
    def closed_input(question):
        raise EOFError

    detector = LocationDetector(powershell_returning("45.581215,5.910249"), fake_web())
    assert run_setup(tmp_path / ".env", tmp_path / "missing", detector, ask=closed_input).city == "Chambéry"
