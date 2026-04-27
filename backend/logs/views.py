import json
import requests
import math
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .services import HOSEngine
from .pdf_generator import ELDPdfGenerator

def _haversine(lon1, lat1, lon2, lat2):
    """Calculate the great circle distance in km between two points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

# ── helpers ───────────────────────────────────────────────────────────────────

def _geocode(name: str):
    """Return (lon, lat) for a place name or None using Photon API."""
    name = name.strip().lower()
    print(f"DEBUG: Calling Photon API for '{name}'...")
    # Photon is more relaxed and faster than Nominatim for development
    # Filtramos por códigos de país: US (EE.UU.) y CA (Canadá)
    url = f"https://photon.komoot.io/api/?q={name}&limit=1"
    
    try:
        headers = {"User-Agent": "SpotterTrucks_App_Global"}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
            
        res = r.json()
        features = res.get("features", [])
        if features:
            props = features[0].get("properties", {})
            cc = props.get('countrycode', '').upper()
            
            # Validación estricta: Solo EE.UU. y Canadá
            if cc not in ['US', 'CA']:
                print(f"DEBUG: Photon Ignored '{name}' -> Found in {cc}, but only US/CA allowed.")
                return None, "OUT_OF_BOUNDS"

            full_name = f"{props.get('name')}, {props.get('state', '')} {props.get('country', '')}".strip()
            coords = features[0]["geometry"]["coordinates"] # [lon, lat]
            result = (float(coords[0]), float(coords[1]))
            print(f"DEBUG: Photon Success for '{name}' -> Found: '{full_name}' at {result}")
            return result, None
            
        print(f"DEBUG: Photon Empty Result for '{name}'")
        return None, "NOT_FOUND"
    except Exception as e:
        print(f"DEBUG: Photon Exception for '{name}': {e}")
        return None, "ERROR"


def _osrm_route(lon1, lat1, lon2, lat2):
    """Call OSRM and return (distance_km, duration_mins, coords) or None."""
    key = f"{lon1},{lat1};{lon2},{lat2}"
    print(f"DEBUG: Calling OSRM for {key}...")
    url = (
        f"http://router.project-osrm.org/route/v1/driving/{key}"
        f"?overview=full&geometries=geojson"
    )
    try:
        data = requests.get(url, timeout=15).json()
        if data.get("code") != "Ok":
            print(f"DEBUG: OSRM Error: {data.get('code')}")
            return None
        route  = data["routes"][0]
        dist   = route["distance"] / 1000.0
        dur    = int(route["duration"] / 60)
        coords = route["geometry"]["coordinates"]
        dist_miles = dist * 0.621371
        
        # Distancia física mínima (línea recta)
        min_dist_km = _haversine(lon1, lat1, lon2, lat2)
        
        print(f"DEBUG: OSRM Result -> Road: {dist:.1f} km, Air: {min_dist_km:.1f} km, Points: {len(coords)}")

        # 1. Bloquear si la distancia física mínima es mayor a 4000 km (Océanos)
        if min_dist_km > 4000:
            print(f"DEBUG: OSRM Error: Straight line distance too long ({min_dist_km:.1f} km).")
            return None

        # 2. Bloquear si la distancia de OSRM es sospechosamente menor que la línea recta
        if dist < (min_dist_km * 0.8):
            print(f"DEBUG: OSRM Error: Impossible route distance.")
            return None
            
        # 3. Bloquear si la ruta es demasiado simple para su distancia
        if dist > 500 and len(coords) < 100:
            print(f"DEBUG: OSRM Error: Geometry too simple.")
            return None

        return dist, dur, coords
    except Exception as e:
        print(f"DEBUG: OSRM Exception: {e}")
        return None


# ── views ─────────────────────────────────────────────────────────────────────

@csrf_exempt
def calculate_logs(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    current_loc  = data.get("current_loc", "").strip()
    pickup_loc   = data.get("pickup_loc", "").strip()
    dropoff_loc  = data.get("dropoff_loc", "").strip()
    cycle_used   = float(data.get("cycle_used", 0) or 0)
    start_time   = data.get("start_time", "")

    if not all([current_loc, pickup_loc, dropoff_loc, start_time]):
        return JsonResponse({"error": "Missing required fields"}, status=400)

    # ── Geocoding ─────────────────────────────────────────────────────────────
    c_res, c_err = _geocode(current_loc)
    p_res, p_err = _geocode(pickup_loc)
    d_res, d_err = _geocode(dropoff_loc)

    errors = [c_err, p_err, d_err]
    if "OUT_OF_BOUNDS" in errors:
        return JsonResponse(
            {"error": "Location outside permitted area (US & Canada only)."}, status=400
        )

    if not all([c_res, p_res, d_res]):
        return JsonResponse(
            {"error": "One or more locations not found. Please check spelling."}, status=400
        )

    c_coords, p_coords, d_coords = c_res, p_res, d_res

    # ── OSRM routing ─────────────────────────────────────────────────────────
    leg1 = _osrm_route(*c_coords, *p_coords)
    leg2 = _osrm_route(*p_coords, *d_coords)

    if not leg1 or not leg2:
        return JsonResponse(
            {"error": "No road connection found between one or more points."}, status=400
        )

    dist1, dur1, coords1 = leg1
    dist2, dur2, coords2 = leg2

    # ── HOS Engine ────────────────────────────────────────────────────────────
    engine = HOSEngine(
        dur_to_pickup     = dur1,
        dist_to_pickup    = dist1,
        dur_to_dropoff    = dur2,
        dist_to_dropoff   = dist2,
        start_time_iso    = start_time,
        locations         = {
            "current": current_loc,
            "pickup":  pickup_loc,
            "dropoff": dropoff_loc,
        },
        cycle_used_hrs    = cycle_used,
        coords_to_pickup  = coords1,
        coords_to_dropoff = coords2,
    )
    logs = engine.generate_log()

    # Combined geometry for map (leg1 + leg2, [lon,lat])
    full_coords = coords1 + coords2

    # Stop markers for the map
    stop_markers = _extract_stop_markers(logs)

    return JsonResponse({
        "logs": logs,
        "route": {
            "distance_km":    round(dist1 + dist2, 2),
            "distance_miles": round((dist1 + dist2) * 0.621371, 2),
            "duration_mins":  dur1 + dur2,
            "coordinates":    full_coords,
            "pickup_coords":  [p_coords[1], p_coords[0]],   # [lat, lon] for Leaflet
        },
        "stop_markers": stop_markers,
    })


def _extract_stop_markers(logs_by_day: dict) -> list:
    """Extract notable stops (fuel, breaks, inspections) from the log events."""
    markers = []
    for day_events in logs_by_day.values():
        for ev in day_events:
            action = ev.get("action", "")
            if any(k in action for k in ("Fueling", "Break", "Sleeper", "Inspection", "Loading", "Unloading")):
                markers.append({
                    "time":     ev["start"],
                    "action":   action,
                    "location": ev.get("location", ""),
                    "remark":   ev.get("remark", ""),
                })
    return markers


@csrf_exempt
def generate_pdf(request):
    """Generate and return a multi-page Driver's Daily Log PDF."""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    logs_by_day  = data.get("logs", {})
    route        = data.get("route", {})
    driver_info  = data.get("driver_info", {})

    if not logs_by_day:
        return JsonResponse({"error": "No log data provided"}, status=400)

    # Enrich driver_info with from/to and mileage for the PDF header
    driver_info.setdefault("from_loc", data.get("current_loc", ""))
    driver_info.setdefault("to_loc",   data.get("dropoff_loc", ""))

    # Auto-fill mileage from calculated route
    miles = route.get("distance_miles", 0)
    if miles:
        driver_info.setdefault("total_miles_driving", miles)
        driver_info.setdefault("total_mileage",       miles)

    try:
        gen       = ELDPdfGenerator(driver_info, logs_by_day, route)
        pdf_bytes = gen.generate()
    except Exception as exc:
        return JsonResponse({"error": f"PDF generation failed: {exc}"}, status=500)

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="drivers_daily_log.pdf"'
    return response