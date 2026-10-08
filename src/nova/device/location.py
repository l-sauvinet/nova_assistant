"""Detects where the user is. Runs on the user's machine (future Tauri side), never on the backend."""

import subprocess
from collections.abc import Callable
from dataclasses import dataclass

import httpx

USER_AGENT = "NOVA-assistant/0.1"
NOMINATIM_URL = "https://nominatim.openstreetmap.org"
IP_GEOLOCATION_URL = "https://ipinfo.io/json"

WINDOWS_LOCATION_SCRIPT = """
Add-Type -AssemblyName System.Device
$watcher = New-Object System.Device.Location.GeoCoordinateWatcher
$watcher.Start()
$waited = 0
while (($watcher.Status -ne 'Ready') -and ($watcher.Permission -ne 'Denied') -and ($waited -lt 150)) {
    Start-Sleep -Milliseconds 100; $waited++
}
$position = $watcher.Position.Location
if ($watcher.Permission -eq 'Denied') { 'DENIED' }
elseif ($position.IsUnknown) { 'UNKNOWN' }
else {
    $culture = [cultureinfo]::InvariantCulture
    "$($position.Latitude.ToString($culture)),$($position.Longitude.ToString($culture))"
}
"""

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class Location:
    city: str
    region: str
    country: str
    latitude: float
    longitude: float
    source: str

    def describe(self) -> str:
        place = ", ".join(part for part in (self.city, self.region, self.country) if part)
        return f"{place} ({self.latitude:.4f}, {self.longitude:.4f})"


class LocationDetector:
    def __init__(
        self,
        run_command: CommandRunner | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.run_command = run_command or subprocess.run
        self.http_client = http_client or httpx.Client(timeout=15, headers={"User-Agent": USER_AGENT})

    def detect(self) -> Location | None:
        """Windows location service first (precise), IP geolocation as a fallback (often only approximate)."""
        coordinates = self.windows_coordinates()
        if coordinates is not None:
            place = self.reverse_geocode(*coordinates)
            if place is not None:
                return place
        return self.ip_location()

    def windows_coordinates(self) -> tuple[float, float] | None:
        try:
            completed = self.run_command(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_LOCATION_SCRIPT],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=40,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return parse_coordinates(completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else "")

    def reverse_geocode(self, latitude: float, longitude: float) -> Location | None:
        data = self._get_json(
            f"{NOMINATIM_URL}/reverse",
            {"format": "jsonv2", "lat": latitude, "lon": longitude, "zoom": 10, "accept-language": "fr"},
        )
        if not isinstance(data, dict) or "address" not in data:
            return None
        return location_from_nominatim(data["address"], latitude, longitude, source="windows")

    def geocode(self, place_name: str) -> Location | None:
        results = self._get_json(
            f"{NOMINATIM_URL}/search",
            {"format": "jsonv2", "q": place_name, "limit": 1, "addressdetails": 1, "accept-language": "fr"},
        )
        if not results:
            return None
        best = results[0]
        return location_from_nominatim(
            best.get("address", {}), float(best["lat"]), float(best["lon"]), source="manual"
        )

    def ip_location(self) -> Location | None:
        data = self._get_json(IP_GEOLOCATION_URL, {})
        coordinates = parse_coordinates(data.get("loc", "")) if isinstance(data, dict) else None
        if coordinates is None:
            return None
        return Location(
            city=data.get("city", ""),
            region=data.get("region", ""),
            country=data.get("country", ""),
            latitude=coordinates[0],
            longitude=coordinates[1],
            source="ip",
        )

    def _get_json(self, url: str, params: dict) -> object:
        try:
            response = self.http_client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            return None


def parse_coordinates(text: str) -> tuple[float, float] | None:
    parts = text.strip().split(",")
    if len(parts) != 2:
        return None
    try:
        latitude, longitude = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def location_from_nominatim(address: dict, latitude: float, longitude: float, source: str) -> Location:
    city = next(
        (address[key] for key in ("city", "town", "village", "municipality", "hamlet") if address.get(key)), ""
    )
    return Location(
        city=city,
        region=address.get("county") or address.get("state", ""),
        country=address.get("country", ""),
        latitude=latitude,
        longitude=longitude,
        source=source,
    )


def location_context(location: Location) -> str:
    return (
        f"The user is located in {location.describe()}. Use this place for weather and any local question "
        f"unless the user names another one; never ask where they are. For weather, fetch "
        f"https://wttr.in/{location.latitude:.4f},{location.longitude:.4f}?format=j1&lang=fr"
    )
