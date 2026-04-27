# ============================================================================
# INSTRUCTION: Copy ALL these functions to your views.py
# Replace old versions of _haversine and _osrm_route
# ============================================================================

import json
import requests
import math
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .services import HOSEngine
from .pdf_generator import ELDPdfGenerator


# ════════════════════════════════════════════════════════════════════════════════
# FUNCTION 1: Haversine (IMPROVED - Comments added)
# ════════════════════════════════════════════════════════════════════════════════

def _haversine(lon1, lat1, lon2, lat2):
    """
    Calculates straight-line distance (great circle) between two points.
    
    This function is used to:
    1. Detect if there is ocean between two points
    2. Validate that the calculated route is geometrically possible
    3. Verify suspicious jumps in coordinates
    
    Args:
        lon1, lat1: Initial Longitude and Latitude
        lon2, lat2: Final Longitude and Latitude
    
    Returns:
        float: Distance in kilometers (straight line/air)
    """
    R = 6371.0  # Earth radius in km
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c


# ════════════════════════════════════════════════════════════════════════════════
# FUNCTION 2: Detect water crossings (NEW)
# ════════════════════════════════════════════════════════════════════════════════

def _route_crosses_water(coords):
    """
    Detects if the route has suspicious jumps indicating an ocean crossing.
    
    Logic:
    - Roads don't have jumps > 200 km between consecutive points
    - If we find > 2 such jumps, the route probably crosses water
    
    Args:
        coords: List of [lon, lat] from OSRM route
    
    Returns:
        bool: True if water crossings detected, False if valid
    """
    
    if not coords or len(coords) < 2:
        return False
    
    max_jump_allowed = 200  # km
    large_jumps = 0
    
    # Check each consecutive segment of the route
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]
        
        distance = _haversine(lon1, lat1, lon2, lat2)
        
        if distance > max_jump_allowed:
            large_jumps += 1
            print(f"DEBUG: ⚠️  Large jump detected: {distance:.1f} km between point {i} and {i+1}")
    
    # If there are more than 2 large jumps, something is wrong
    if large_jumps > 2:
        print(f"DEBUG: Detected {large_jumps} large jumps - probably water")
        return True
    
    return False


# ════════════════════════════════════════════════════════════════════════════════
# FUNCTION 3: OSRM Route (IMPROVED - MAIN VERSION)
# ════════════════════════════════════════════════════════════════════════════════

def _osrm_route(lon1, lat1, lon2, lat2, validate_real_route=True):
    """
    Gets OSRM route with exhaustive validations.
    
    Validates 6 levels to avoid "invented" routes:
    1. OSRM reports "NoRoute"
    2. Straight-line distance > 4000 km (ocean)
    3. Route < 80% straight line (impossible geometry)
    4. Long route without enough points (too simple)
    5. Jumps > 200 km in coordinates (water crossings)
    6. Average speed > 150 km/h (impossible on land)
    
    Args:
        lon1, lat1: Initial Longitude, Latitude
        lon2, lat2: Final Longitude, Latitude
        validate_real_route: If False, skips validations (debug)
    
    Returns:
        tuple: (dist_km, dur_mins, coordinates)
        or None if the route is not valid
    """
    
    key = f"{lon1},{lat1};{lon2},{lat2}"
    print(f"DEBUG: 🔄 Calling OSRM for {key}...")
    
    url = (
        f"http://router.project-osrm.org/route/v1/driving/{key}"
        f"?overview=full&geometries=geojson&steps=true&annotations=distance,duration"
    )
    
    try:
        # Request to OSRM
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        # ════════════════════════════════════════════════════════════════
        # VALIDATION 1: Did OSRM find a route?
        # ════════════════════════════════════════════════════════════════
        if data.get("code") != "Ok":
            error_code = data.get("code", "Unknown")
            print(f"DEBUG: ❌ OSRM Error Code: {error_code}")
            
            # Specific codes indicate NO real route exists
            if error_code in ["NoRoute", "NoMatch"]:
                print(f"DEBUG: ❌ No real route available (OSRM: {error_code})")
            
            return None
        
        # Extract route data
        route = data["routes"][0]
        dist_km = route["distance"] / 1000.0
        dur_mins = int(route["duration"] / 60)
        coords = route["geometry"]["coordinates"]
        
        # Calculate straight-line distance (reference)
        min_dist_km = _haversine(lon1, lat1, lon2, lat2)
        
        print(f"DEBUG: 📊 OSRM Result -> Road: {dist_km:.1f} km, Air: {min_dist_km:.1f} km, Points: {len(coords)}")
        
        # If not validating, return directly (debug mode)
        if not validate_real_route:
            print(f"DEBUG: ⚠️  Validation disabled - returning route without verification")
            return dist_km, dur_mins, coords
        
        # ════════════════════════════════════════════════════════════════
        # VALIDATION 3: Route shorter than straight line (impossible)
        # ════════════════════════════════════════════════════════════════
        if dist_km < (min_dist_km * 0.8):
            print(f"DEBUG: ❌ REJECTED - Route {dist_km:.1f} km < 80% straight line {min_dist_km:.1f} km")
            print(f"DEBUG: (A road route cannot be shorter than a straight line)")
            return None
        
        # ════════════════════════════════════════════════════════════════
        # VALIDATION 4: Long route with few points (too simple)
        # ════════════════════════════════════════════════════════════════
        if dist_km > 500 and len(coords) < 100:
            print(f"DEBUG: ❌ REJECTED - Long route ({dist_km:.1f} km) with few points ({len(coords)})")
            print(f"DEBUG: (A 500+ km route must have many curves)")
            return None
        
        # ════════════════════════════════════════════════════════════════
        # VALIDATION 5: Detect water crossings (jumps > 200 km)
        # ════════════════════════════════════════════════════════════════
        if _route_crosses_water(coords):
            print(f"DEBUG: ❌ REJECTED - Route crosses significant water")
            return None
        
        # ════════════════════════════════════════════════════════════════
        # VALIDATION 6: Realistic average speed
        # ════════════════════════════════════════════════════════════════
        if dur_mins > 0:
            average_speed = (dist_km / (dur_mins / 60))
            
            # Warning: very low speed (traffic, mountain, etc)
            if average_speed < 20:
                print(f"DEBUG: ⚠️  Very low speed: {average_speed:.1f} km/h (traffic or mountain)")
            
            # Rejection: impossible speed (> 150 km/h on land)
            if average_speed > 150:
                print(f"DEBUG: ❌ REJECTED - Impossible speed: {average_speed:.1f} km/h")
                return None
        
        # ════════════════════════════════════════════════════════════════
        # ALL VALIDATIONS PASSED ✅
        # ════════════════════════════════════════════════════════════════
        
        if dur_mins > 0:
            average_speed = (dist_km / (dur_mins / 60))
            print(f"DEBUG: ✅ VALID ROUTE - {dist_km:.1f} km in {dur_mins} min ({average_speed:.1f} km/h)")
        else:
            print(f"DEBUG: ✅ VALID ROUTE - {dist_km:.1f} km")
        
        return dist_km, dur_mins, coords
    
    # ════════════════════════════════════════════════════════════════════
    # EXCEPTION HANDLING (SPECIFIC)
    # ════════════════════════════════════════════════════════════════════
    
    except requests.exceptions.Timeout:
        print(f"DEBUG: ❌ OSRM Timeout - No response in 15 seconds")
        return None
    
    except requests.exceptions.ConnectionError as e:
        print(f"DEBUG: ❌ OSRM Connection Error - Is OSRM available? Error: {e}")
        return None
    
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: ❌ OSRM Network Exception: {e}")
        return None
    
    except json.JSONDecodeError:
        print(f"DEBUG: ❌ OSRM Response is not valid JSON")
        return None
    
    except (KeyError, IndexError) as e:
        print(f"DEBUG: ❌ OSRM Response structure error: {e}")
        return None
    
    except Exception as e:
        print(f"DEBUG: ❌ OSRM Unexpected Exception: {e}")
        return None


# ════════════════════════════════════════════════════════════════════════════════
# FUNCTION 4: Geocode (IMPROVED)
# ════════════════════════════════════════════════════════════════════════════════

def _geocode(name: str):
    """
    Converts place name to coordinates (lon, lat).
    
    Uses Photon API which is fast and reliable.
    
    Args:
        name: Name of the place (e.g.: "Miami, FL")
    
    Returns:
        tuple: ((lon, lat), error_code)
        - If success: ((lon, lat), None)
        - If not found: (None, "NOT_FOUND")
        - If error: (None, "ERROR" or "TIMEOUT")
    """
    
    name = name.strip().lower()
    print(f"DEBUG: 🔍 Geocoding '{name}'...")
    
    url = f"https://photon.komoot.io/api/?q={name}&limit=1"
    
    try:
        headers = {"User-Agent": "SpotterTrucks_App_Global"}
        r = requests.get(url, headers=headers, timeout=10)
        
        if r.status_code != 200:
            print(f"DEBUG: ❌ Photon HTTP {r.status_code}")
            return None, "HTTP_ERROR"
        
        res = r.json()
        features = res.get("features", [])
        
        if not features:
            print(f"DEBUG: ❌ Not found: '{name}'")
            return None, "NOT_FOUND"
        
        # Extract first result
        props = features[0].get("properties", {})
        
        # Extract coordinates [lon, lat]
        coords = features[0]["geometry"]["coordinates"]
        result = (float(coords[0]), float(coords[1]))
        
        full_name = f"{props.get('name')}, {props.get('state', '')} {props.get('country', '')}".strip()
        print(f"DEBUG: ✅ Geocoded '{name}' -> {full_name}")
        
        return result, None
    
    except requests.exceptions.Timeout:
        print(f"DEBUG: ❌ Photon Timeout for '{name}'")
        return None, "TIMEOUT"
    
    except Exception as e:
        print(f"DEBUG: ❌ Photon Exception for '{name}': {e}")
        return None, "ERROR"


# ════════════════════════════════════════════════════════════════════════════════
# FUNCTION 5: Extract Stop Markers (No changes)
# ════════════════════════════════════════════════════════════════════════════════

def _extract_stop_markers(logs_by_day: dict) -> list:
    """Extracts stop markers from the event log."""
    markers = []
    for day_events in logs_by_day.values():
        for ev in day_events:
            action = ev.get("action", "")
            if any(k in action for k in ("Fueling", "Break", "Sleeper", "Inspection", "Loading", "Unloading")):
                markers.append({
                    "time": ev["start"],
                    "action": action,
                    "location": ev.get("location", ""),
                    "remark": ev.get("remark", ""),
                })
    return markers


# ════════════════════════════════════════════════════════════════════════════════
# VIEW 1: Calculate Logs (IMPROVED)
# ════════════════════════════════════════════════════════════════════════════════

@csrf_exempt
def calculate_logs(request):
    """
    Calculates driving logs (HOS) between locations.
    
    With exhaustive validations of real routes.
    
    Request JSON:
    {
        "current_loc": "Medellín, Colombia",
        "pickup_loc": "Bogotá, Colombia",
        "dropoff_loc": "Cali, Colombia",
        "cycle_used": 0,
        "start_time": "2024-01-15T08:00:00Z"
    }
    """
    
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Extract parameters
    current_loc = data.get("current_loc", "").strip()
    pickup_loc = data.get("pickup_loc", "").strip()
    dropoff_loc = data.get("dropoff_loc", "").strip()
    cycle_used = float(data.get("cycle_used", 0) or 0)
    start_time = data.get("start_time", "")

    # Validate required fields
    if not all([current_loc, pickup_loc, dropoff_loc, start_time]):
        return JsonResponse({"error": "Missing required fields"}, status=400)

    # ── STEP 1: GEOCODING ──────────────────────────────────────────────
    print(f"DEBUG: 📍 STEP 1 - Geocoding locations...")
    
    c_res, c_err = _geocode(current_loc)
    p_res, p_err = _geocode(pickup_loc)
    d_res, d_err = _geocode(dropoff_loc)

    # Check if all were found
    if not all([c_res, p_res, d_res]):
        print(f"DEBUG: ❌ A location was not found")
        return JsonResponse(
            {"error": "One or more locations not found. Please check spelling."}, 
            status=400
        )

    c_coords, p_coords, d_coords = c_res, p_res, d_res

    # ── STEP 2: ROUTING WITH OSRM ──────────────────────────────────────
    print(f"DEBUG: 🗺️  STEP 2 - Calculating routes with OSRM...")
    
    leg1 = _osrm_route(*c_coords, *p_coords, validate_real_route=True)
    leg2 = _osrm_route(*p_coords, *d_coords, validate_real_route=True)

    if not leg1 or not leg2:
        print(f"DEBUG: ❌ One or both routes are not valid")
        return JsonResponse(
            {"error": "No valid road connection found between one or more points. Check if locations are accessible by road."}, 
            status=400
        )

    dist1, dur1, coords1 = leg1
    dist2, dur2, coords2 = leg2

    # ── STEP 3: HOS ENGINE ────────────────────────────────────────────
    print(f"DEBUG: 📋 STEP 3 - Generating HOS logs...")
    
    engine = HOSEngine(
        dur_to_pickup=dur1,
        dist_to_pickup=dist1,
        dur_to_dropoff=dur2,
        dist_to_dropoff=dist2,
        start_time_iso=start_time,
        locations={
            "current": current_loc,
            "pickup": pickup_loc,
            "dropoff": dropoff_loc,
        },
        cycle_used_hrs=cycle_used,
        coords_to_pickup=coords1,
        coords_to_dropoff=coords2,
    )
    logs = engine.generate_log()

    # Combine geometry
    full_coords = coords1 + coords2
    stop_markers = _extract_stop_markers(logs)

    print(f"DEBUG: ✅ Successful response - Total route: {dist1+dist2:.1f} km")
    
    return JsonResponse({
        "logs": logs,
        "route": {
            "distance_km": round(dist1 + dist2, 2),
            "distance_miles": round((dist1 + dist2) * 0.621371, 2),
            "duration_mins": dur1 + dur2,
            "coordinates": full_coords,
            "pickup_coords": [p_coords[1], p_coords[0]],
        },
        "stop_markers": stop_markers,
    })


# ════════════════════════════════════════════════════════════════════════════════
# VIEW 2: Generate PDF (No changes)
# ════════════════════════════════════════════════════════════════════════════════

@csrf_exempt
def generate_pdf(request):
    """Generate and return a multi-page Driver's Daily Log PDF."""
    
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    logs_by_day = data.get("logs", {})
    route = data.get("route", {})
    driver_info = data.get("driver_info", {})

    if not logs_by_day:
        return JsonResponse({"error": "No log data provided"}, status=400)

    driver_info.setdefault("from_loc", data.get("current_loc", ""))
    driver_info.setdefault("to_loc", data.get("dropoff_loc", ""))

    miles = route.get("distance_miles", 0)
    if miles:
        driver_info.setdefault("total_miles_driving", miles)
        driver_info.setdefault("total_mileage", miles)

    try:
        gen = ELDPdfGenerator(driver_info, logs_by_day, route)
        pdf_bytes = gen.generate()
    except Exception as exc:
        return JsonResponse({"error": f"PDF generation failed: {exc}"}, status=500)

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="drivers_daily_log.pdf"'
    return response
