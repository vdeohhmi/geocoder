import streamlit as st
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

@st.cache_data(ttl=24*3600)
def get_location(query: str):
    """
    Geocode the given query string and return a (latitude, longitude) tuple,
    or None if not found.
    """
    geolocator = Nominatim(user_agent="institute_locator")
    try:
        loc = geolocator.geocode(query)
    except GeocoderTimedOut:
        return None
    if loc:
        return loc.latitude, loc.longitude
    return None

def main():
    st.title("🏫 Institute Geolocation Finder")
    st.write("Enter an institute name or code below and hit **Find** to get its latitude and longitude.")
    
    institute_query = st.text_input("Institute Name or Code")
    
    if st.button("Find"):
        if not institute_query.strip():
            st.warning("Please enter an institute name or code to search.")
            return
        
        result = get_location(institute_query)
        if result:
            lat, lon = result
            st.success(f"**Latitude:** {lat:.6f}    **Longitude:** {lon:.6f}")
            # Display on a map
            st.map({"lat": [lat], "lon": [lon]})
        else:
            st.error("⚠️ Could not find that institute. Please check the spelling or try a different query.")

if __name__ == "__main__":
    main()
