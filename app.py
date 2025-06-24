import sys
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

def geocode(name):
    geolocator = Nominatim(user_agent="institute_geocoder", timeout=10)
    try:
        loc = geolocator.geocode(name)
        if loc:
            return loc.latitude, loc.longitude
    except GeocoderTimedOut:
        return geocode(name)
    return None, None

if __name__ == "__main__":
    if len(sys.argv) > 1:
        name = " ".join(sys.argv[1:])
    else:
        name = input("Enter institute name: ").strip()
    lat, lon = geocode(name)
    if lat is not None:
        print(f"Latitude: {lat}\nLongitude: {lon}")
    else:
        print("Coordinates not found")
