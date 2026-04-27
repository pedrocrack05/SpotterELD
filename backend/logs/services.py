from datetime import datetime, time, timedelta
import math
import requests

# ── Constants ────────────────────────────────────────────────────────────────
FUEL_INTERVAL_KM = 1609.34   # 1 000 miles
DRIVE_LIMIT_MINS = 660       # 11 h
DUTY_WINDOW_MINS = 840       # 14 h
BREAK_AFTER_MINS = 480       # 8 h on duty without 30-min break
SLEEP_MINS       = 600       # 10 h sleeper berth
CYCLE_LIMIT_MINS = 4200      # 70 h / 8 days
RESTART_MINS      = 2040      # 34 h for cycle restart


# ── Helpers ───────────────────────────────────────────────────────────────────

def snap_to_quarter(dt: datetime) -> datetime:
    """Floor to the nearest 15-minute boundary."""
    return dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)


def haversine_km(lon1, lat1, lon2, lat2) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi   = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def interpolate_point(coords: list, target_km: float) -> list:
    """Return [lon, lat] at `target_km` along the polyline `coords`."""
    if not coords or len(coords) < 2:
        return coords[0] if coords else [0.0, 0.0]
    accumulated = 0.0
    for i in range(len(coords) - 1):
        p1, p2 = coords[i], coords[i + 1]
        seg_km = haversine_km(p1[0], p1[1], p2[0], p2[1])
        if accumulated + seg_km >= target_km:
            frac = (target_km - accumulated) / seg_km if seg_km > 0 else 0.0
            return [
                p1[0] + frac * (p2[0] - p1[0]),
                p1[1] + frac * (p2[1] - p1[1]),
            ]
        accumulated += seg_km
    return list(coords[-1])


def reverse_geocode(lon: float, lat: float) -> str:
    """Return 'City, State' from coordinates via Photon (more reliable for dev)."""
    try:
        url = f"https://photon.komoot.io/reverse?lon={lon}&lat={lat}"
        headers = {"User-Agent": "SpotterTrucks_App_Debug_Global"}
        r = requests.get(url, headers=headers, timeout=6)
        if r.status_code != 200:
            return "En Route"
            
        res = r.json()
        features = res.get("features", [])
        if not features:
            return "En Route"
            
        props = features[0].get("properties", {})
        city = (
            props.get("city")
            or props.get("town")
            or props.get("village")
            or props.get("locality")
            or props.get("county", "Unknown")
        )
        state = props.get("state", "")
        return f"{city}, {state}" if state else city
    except Exception:
        return "En Route"


# ── HOS Engine ────────────────────────────────────────────────────────────────

class HOSEngine:
    """
    Full HOS/ELD simulation engine.

    Parameters
    ----------
    dur_to_pickup     : drive time in minutes to pickup
    dist_to_pickup    : distance in km to pickup
    dur_to_dropoff    : drive time in minutes to dropoff
    dist_to_dropoff   : distance in km to dropoff
    start_time_iso    : ISO 8601 departure datetime string
    locations         : dict with 'current', 'pickup', 'dropoff' keys
    cycle_used_hrs    : hours already used in the current 70/8 cycle
    coords_to_pickup  : list of [lon, lat] waypoints for leg 1
    coords_to_dropoff : list of [lon, lat] waypoints for leg 2
    """

    def __init__(
        self,
        dur_to_pickup: int,
        dist_to_pickup: float,
        dur_to_dropoff: int,
        dist_to_dropoff: float,
        start_time_iso: str,
        locations: dict,
        cycle_used_hrs: float = 0,
        coords_to_pickup: list = None,
        coords_to_dropoff: list = None,
    ):
        self.locs              = locations
        self.dur_to_pickup     = dur_to_pickup
        self.dist_to_pickup    = dist_to_pickup
        self.dur_to_dropoff    = dur_to_dropoff
        self.dist_to_dropoff   = dist_to_dropoff
        self.coords_pickup     = coords_to_pickup  or []
        self.coords_dropoff    = coords_to_dropoff or []

        # Snap departure to 15-min boundary
        raw = datetime.fromisoformat(start_time_iso.replace("Z", ""))
        self.current_time = snap_to_quarter(raw)
        
        # Save preferred start time for subsequent days
        self.start_hour   = self.current_time.hour
        self.start_min    = self.current_time.minute

        # HOS clocks (minutes)
        self.drive_clock  = 0
        self.duty_clock   = 0
        self.meal_clock   = 0          # minutes since last 30-min break
        self.fuel_km      = 0.0        # km since last fuel stop
        self.cycle_clock  = int(cycle_used_hrs * 60)

        # Route tracking
        self._seg_coords  = []         # waypoints of the current drive leg
        self._seg_dist_km = 0.0        # total distance of current leg
        self._traveled_km = 0.0        # km driven so far in current leg

        self._geo_cache: dict = {}
        self.events: list = []

    # ── private helpers ───────────────────────────────────────────────────────

    def _city_now(self) -> str:
        if not self._seg_coords:
            return self.locs.get("current", "")
        pt = interpolate_point(self._seg_coords, self._traveled_km)
        key = f"{pt[0]:.3f},{pt[1]:.3f}"
        if key not in self._geo_cache:
            self._geo_cache[key] = reverse_geocode(pt[0], pt[1])
        return self._geo_cache[key]

    def _add(self, status: int, minutes: int, action: str, location: str = "", dist_km: float = 0.0):
        """Append one or more events, splitting at midnight boundaries."""
        if minutes <= 0:
            return
        remark = f"{location} - {action}" if location else action
        end_dt = self.current_time + timedelta(minutes=minutes)
        cur    = self.current_time
        
        # Calculate proportional distance per minute if provided
        km_per_min = dist_km / minutes if minutes > 0 else 0.0

        while cur.date() < end_dt.date():
            midnight = datetime.combine(cur.date() + timedelta(days=1), time.min)
            chunk = int((midnight - cur).total_seconds() / 60)
            if chunk > 0:
                self.events.append({
                    "date":         cur.date().isoformat(),
                    "status":       status,
                    "start":        cur.isoformat(),
                    "end":          midnight.isoformat(),
                    "duration_mins": chunk,
                    "distance_km":  chunk * km_per_min,
                    "remark":       remark,
                    "location":     location,
                    "action":       action,
                })
            cur = midnight

        remaining = int((end_dt - cur).total_seconds() / 60)
        if remaining > 0:
            self.events.append({
                "date":         cur.date().isoformat(),
                "status":       status,
                "start":        cur.isoformat(),
                "end":          end_dt.isoformat(),
                "duration_mins": remaining,
                "distance_km":  remaining * km_per_min,
                "remark":       remark,
                "location":     location,
                "action":       action,
            })
        self.current_time = end_dt

    def _on_duty(self, minutes: int, action: str, location: str):
        self._add(4, minutes, action, location)
        self.duty_clock  += minutes
        self.meal_clock  += minutes
        self.cycle_clock += minutes

    def _sleep(self, location: str):
        self._add(2, SLEEP_MINS, "Sleeper Berth", location)
        self.drive_clock = 0
        self.duty_clock  = 0
        self.meal_clock  = 0

    def _restart_cycle(self, location: str):
        """34-hour cycle restart (Off Duty)."""
        self._add(1, RESTART_MINS, "34-Hour Cycle Restart", location)
        self.drive_clock = 0
        self.duty_clock  = 0
        self.meal_clock  = 0
        self.cycle_clock = 0

    def _break(self, location: str):
        """30-minute Off Duty break."""
        self._add(1, 30, "30 Min Break", location)
        self.meal_clock = 0

    def _fuel(self, location: str):
        self._on_duty(30, "Fueling", location)
        self.fuel_km = 0.0

    def _wait_until_start(self):
        """Wait (Off Duty) until the preferred start time of the day if it's currently earlier."""
        target = self.current_time.replace(hour=self.start_hour, minute=self.start_min, second=0, microsecond=0)
        
        # If current time is before the preferred hour of the SAME day, wait.
        if self.current_time < target:
            wait_mins = int((target - self.current_time).total_seconds() / 60)
            if wait_mins > 0:
                self._add(1, wait_mins, "Waiting for preferred start time", self._city_now())

    def _drive_step(self, minutes: int, to_loc: str, km_per_min: float):
        dist = minutes * km_per_min
        self._add(3, minutes, f"Driving to {to_loc}", "", dist_km=dist)
        self.drive_clock  += minutes
        self.duty_clock   += minutes
        self.meal_clock   += minutes
        self.cycle_clock  += minutes
        self.fuel_km      += dist
        self._traveled_km += dist

    # ── drive segment ─────────────────────────────────────────────────────────

    def _process_drive(self, total_mins: int, total_km: float, to_loc: str, coords: list):
        """Simulate a full drive leg with all HOS compliance checks."""
        self._seg_coords  = coords
        self._seg_dist_km = total_km
        self._traveled_km = 0.0
        km_per_min = (total_km / total_mins) if total_mins > 0 else 0.0
        remaining  = total_mins

        while remaining > 0:
            # ── compliance checks ──────────────────────────────────────────
            if self.cycle_clock >= CYCLE_LIMIT_MINS:
                self._restart_cycle(self._city_now())
                self._wait_until_start()
                continue
            if self.drive_clock >= DRIVE_LIMIT_MINS:
                self._sleep(self._city_now())
                self._wait_until_start()
                continue
            if self.duty_clock >= DUTY_WINDOW_MINS:
                self._sleep(self._city_now())
                self._wait_until_start()
                continue
            if self.meal_clock >= BREAK_AFTER_MINS:
                self._break(self._city_now())
                continue
            if self.fuel_km >= FUEL_INTERVAL_KM:
                self._fuel(self._city_now())
                continue

            # Calculate the maximum safe step we can take without breaking ANY rule
            # Rule 1: Standard 15-min increment
            # Rule 2: Remaining time for this leg
            # Rule 3: 11h driving limit (DRIVE_LIMIT_MINS - current)
            # Rule 4: 14h duty window (DUTY_WINDOW_MINS - current)
            # Rule 5: 8h break requirement (BREAK_AFTER_MINS - current)
            # Rule 6: 70h cycle limit (CYCLE_LIMIT_MINS - current)
            
            step = min(
                15, 
                remaining,
                max(0, DRIVE_LIMIT_MINS - self.drive_clock),
                max(0, DUTY_WINDOW_MINS - self.duty_clock),
                max(0, BREAK_AFTER_MINS - self.meal_clock),
                max(0, CYCLE_LIMIT_MINS - self.cycle_clock)
            )

            # If step is 0 but we have remaining time, it means a limit was hit exactly
            if step <= 0:
                continue

            self._drive_step(step, to_loc, km_per_min)
            remaining -= step

    # ── public ───────────────────────────────────────────────────────────────

    def generate_log(self) -> dict:
        origin  = self.locs["current"]
        pickup  = self.locs["pickup"]
        dropoff = self.locs["dropoff"]

        # ── 0. Off Duty: Midnight → Departure ────────────────────────────────
        midnight_start = datetime.combine(self.current_time.date(), time.min)
        gap = int((self.current_time - midnight_start).total_seconds() / 60)
        if gap > 0:
            self.events.append({
                "date":         midnight_start.date().isoformat(),
                "status":       1,
                "start":        midnight_start.isoformat(),
                "end":          self.current_time.isoformat(),
                "duration_mins": gap,
                "remark":       f"{origin} - Off Duty",
                "location":     origin,
                "action":       "Off Duty",
            })

        # ── 1. Pre-Trip Inspection (15 min On Duty) ───────────────────────────
        self._on_duty(15, "Pre-Trip Inspection", origin)

        # ── 2. Drive → Pickup ─────────────────────────────────────────────────
        self._process_drive(self.dur_to_pickup, self.dist_to_pickup, pickup, self.coords_pickup)

        # ── 3. Pickup (60 min On Duty — Loading Freight) ──────────────────────
        self._on_duty(60, "Loading Freight", pickup)

        # ── 4. Drive → Dropoff ────────────────────────────────────────────────
        self._process_drive(self.dur_to_dropoff, self.dist_to_dropoff, dropoff, self.coords_dropoff)

        # ── 5. Dropoff (60 min On Duty — Unloading Freight) ──────────────────
        self._on_duty(60, "Unloading Freight", dropoff)

        # ── 6. Post-Trip Inspection (15 min On Duty) ──────────────────────────
        self._on_duty(15, "Post-Trip Inspection", dropoff)

        # ── 7. Off Duty: End → Midnight ───────────────────────────────────────
        end_midnight = datetime.combine(self.current_time.date() + timedelta(days=1), time.min)
        tail = int((end_midnight - self.current_time).total_seconds() / 60)
        if tail > 0:
            self._add(1, tail, "Off Duty", dropoff)

        # ── Group by date ─────────────────────────────────────────────────────
        by_day: dict = {}
        for ev in sorted(self.events, key=lambda e: e["start"]):
            d = ev["date"]
            if d not in by_day:
                by_day[d] = []
            by_day[d].append(ev)
        return by_day