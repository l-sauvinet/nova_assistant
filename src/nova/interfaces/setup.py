import shutil
from collections.abc import Callable
from pathlib import Path

from dotenv import set_key

from nova.device.location import Location, LocationDetector

SOURCE_LABELS = {
    "windows": "Windows location service",
    "ip": "your internet address (approximate, can be far off)",
    "manual": "your answer",
}

Prompt = Callable[[str], str]


def _ask_or_empty(ask: Prompt, question: str) -> str:
    try:
        return ask(question).strip()
    except EOFError:
        print()
        return ""


def run_setup(
    env_path: Path = Path(".env"),
    example_path: Path = Path(".env.example"),
    detector: LocationDetector | None = None,
    ask: Prompt = input,
) -> Location | None:
    """Installation step: detects the user's location, lets them confirm or correct it, saves it in .env."""
    if not env_path.exists() and example_path.exists():
        shutil.copy(example_path, env_path)
        print(f"Created {env_path} from {example_path}.")

    detector = detector or LocationDetector()
    print("NOVA setup: detecting your location (Windows location service, then internet address)...")
    location = detector.detect()

    if location is not None:
        print(f"Detected: {location.describe()} — via {SOURCE_LABELS.get(location.source, location.source)}.")
        if _ask_or_empty(ask, "Is this correct? [O/n] ").lower() in {"n", "non", "no"}:
            location = None

    while location is None:
        place_name = _ask_or_empty(ask, "Type your city (e.g. 'Chambéry, France'), or leave empty to skip: ")
        if not place_name:
            print("Location skipped. Run `uv run nova setup` any time to set it.")
            return None
        location = detector.geocode(place_name)
        if location is None:
            print(f"Could not find '{place_name}'. Try again with the country.")

    save_location(env_path, location)
    print(f"Location saved in {env_path}: {location.describe()}.")
    return location


def save_location(env_path: Path, location: Location) -> None:
    env_path.touch(exist_ok=True)
    values = {
        "NOVA_LOCATION_CITY": location.city,
        "NOVA_LOCATION_REGION": location.region,
        "NOVA_LOCATION_COUNTRY": location.country,
        "NOVA_LOCATION_LATITUDE": f"{location.latitude:.6f}",
        "NOVA_LOCATION_LONGITUDE": f"{location.longitude:.6f}",
        "NOVA_LOCATION_SOURCE": location.source,
    }
    for key, value in values.items():
        set_key(env_path, key, value)
