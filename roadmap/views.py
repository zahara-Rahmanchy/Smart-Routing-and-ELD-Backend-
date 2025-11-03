from datetime import datetime, timedelta
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
import requests, math

from roadmap.models import Trip
from roadmap.serializers import TripSerializer
from logsheet.models import LogSheet
from logsheet.serializers import LogSheetSerializer


# Geocode address using ORS
def geocode_address(address):
    url = f"{settings.ORS_URL}/geocode/search"
    headers = {"Authorization": settings.ORS_API_KEY}
    params = {"text": address, "size": 1}
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200 and response.json()["features"]:
        coords = response.json()["features"][0]["geometry"]["coordinates"]  # [lon, lat]
        return coords
    return None


# Reduce route points for map
def simplify_coordinates(coords, step=50):
    return coords[::step] + [coords[-1]]


# Get POIs (stops) along the route

def get_stops_along_route(coordinates):
    """
    Fetch real POIs along the route from ORS.
    coordinates: [[lat, lon], [lat, lon], ...]
    Returns: List of stops with label and coordinates.
    """
    url = f"{settings.ORS_URL}/pois"
    headers = {
        "Authorization": settings.ORS_API_KEY,
        "Content-Type": "application/json"
    }
    body = {
    "request": "pois",
    "geometry": {
        "buffer": 1000,
        "geojson": {
            "type": "LineString",
            "coordinates": [[lon, lat] for lat, lon in coordinates]
        }
    },
    "filters": {
        "category_ids": [
            101, 102, 103, 104
        ]
    }}



    try:
        response = requests.post(url, headers=headers, json=body)
        stops = []

        if response.status_code == 200:
            pois = response.json().get("features", [])
            for p in pois:
                stops.append({
                    "label": p["properties"].get("name", "Unknown"),
                    "coords": [
                        p["geometry"]["coordinates"][1],  # lat
                        p["geometry"]["coordinates"][0]   # lon
                    ]
                })
        else:
            print("ORS POIs request failed:", response.status_code, response.text)

        return stops

    except Exception as e:
        print("ORS POIs request exception:", str(e))
        return []
def generate_eld_logs(duration_hours, current_cycle_hours, start_time=None):
   
    logs = {}
    if start_time is None:
        start_time = datetime.now().replace(hour=6, minute=0, second=0, microsecond=0)

    remaining_cycle_hours = max(0, 70 - float(current_cycle_hours))  # assuming 70-hour/8-day rule
    hours_remaining = duration_hours

    driving_limit = 11          # max hours driving in a day
    duty_window = 14            # max driving window in hours
    rest_required = 10          # mandatory off-duty hours
    on_duty_hours = 2.5         # non-driving on-duty work

    current_time = start_time

    while hours_remaining > 0:
        # Determine daily driving window left
        day_key = current_time.strftime("%Y-%m-%d")
        if day_key not in logs:
            logs[day_key] = []

        # Driving hours for this period
        drive_hours = min(driving_limit, hours_remaining)

        # Driving period
        drive_start = current_time
        drive_end = drive_start + timedelta(hours=drive_hours)
        logs[day_key].append({
            "type": "driving",
            "start": drive_start.isoformat(),
            "end": drive_end.isoformat(),
            "hours": round(drive_hours, 2)
        })

        # On-duty period (non-driving tasks)
        on_duty_start = drive_end
        on_duty_end = on_duty_start + timedelta(hours=on_duty_hours)
        on_duty_day = on_duty_start.strftime("%Y-%m-%d")
        if on_duty_day not in logs:
            logs[on_duty_day] = []
        logs[on_duty_day].append({
            "type": "on_duty",
            "start": on_duty_start.isoformat(),
            "end": on_duty_end.isoformat(),
            "hours": on_duty_hours
        })

        # Sleeper/off-duty period
        rest_start = on_duty_end
        rest_end = rest_start + timedelta(hours=rest_required)
        rest_day = rest_start.strftime("%Y-%m-%d")
        if rest_day not in logs:
            logs[rest_day] = []
        logs[rest_day].append({
            "type": "sleeper",
            "start": rest_start.isoformat(),
            "end": rest_end.isoformat(),
            "hours": rest_required
        })

        # Move to next cycle
        current_time = rest_end
        hours_remaining -= drive_hours

    return {
        "remaining_cycle_hours": round(remaining_cycle_hours, 2),
        "logs": logs
    }


class TripView(APIView):
    def post(self, request):
        serializer = TripSerializer(data=request.data)
        if serializer.is_valid():
            trip = serializer.save()

            # ✅ Mandatory: current cycle hours
            current_cycle_hours = request.data.get("current_cycle_hours")
            if current_cycle_hours is None:
                return Response(
                    {"error": "current_cycle_hours is required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Geocode addresses
            start_coords = geocode_address(trip.current_location)
            pickup_coords = geocode_address(trip.pickup_location)
            end_coords = geocode_address(trip.dropoff_location)

            if not all([start_coords, pickup_coords, end_coords]):
                return Response(
                    {"error": "Failed to geocode one or more addresses."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Directions
            start_str = f"{start_coords[0]},{start_coords[1]}"
            end_str = f"{end_coords[0]},{end_coords[1]}"
            ors_url = f"{settings.ORS_URL}/v2/directions/driving-car"
            headers = {"Authorization": settings.ORS_API_KEY}
            params = {"start": start_str, "end": end_str}

            response = requests.get(ors_url, headers=headers, params=params)
            if response.status_code != 200:
                return Response({"error": "Failed to get route data"}, status=status.HTTP_400_BAD_REQUEST)

            data = response.json()
            segment = data["features"][0]["properties"]["segments"][0]
            geometry = data["features"][0]["geometry"]["coordinates"]
            coordinates = [[lat, lon] for lon, lat in geometry]
            simplified_coordinates = simplify_coordinates(coordinates, step=50)

            # ✅ Fetch stops using simplified coordinates
            poi_stops = get_stops_along_route( simplify_coordinates(coordinates, step=200))

            # Default key stops
            stops = [
                {"coords": [start_coords[1], start_coords[0]], "label": "Current Location"},
                {"coords": [pickup_coords[1], pickup_coords[0]], "label": "Pickup Location"},
                {"coords": [end_coords[1], end_coords[0]], "label": "Dropoff Location"},
            ] + poi_stops
            print("poi_stops: ",poi_stops)
            # Distance & Duration
            distance_km = segment["distance"] / 1000
            duration_hours = segment["duration"] / 3600

            # ELD (including cycle hours)
           

            eld_data = generate_eld_logs(duration_hours, current_cycle_hours)

            return Response({
                "trip_id": trip.id,
                "route_summary": {
                    "distance_km": round(distance_km, 2),
                    "duration_hours": round(duration_hours, 2),
                    # "driving_time": round(driving_time, 2),
                    # "rest_time": round(rest_time, 2),
                    # "idle_time": round(idle_time, 2),
                    # "remaining_cycle_hours": remaining_cycle_hours,
                    "coordinates": simplified_coordinates,
                    "stops": stops,
                },
                "logs": eld_data,
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

