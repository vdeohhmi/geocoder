import streamlit as st
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import pandas as pd
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import io

# Set page layout
st.set_page_config(page_title="Institute Geolocation Finder", layout="wide")
st.title("🏫 Institute Geolocation Finder")

# Geolocator setup
geolocator = Nominatim(user_agent="GeoLocatorApp", timeout=10)

# Cache for repeat lookups
@st.cache_data(show_spinner=False)
def cached_geocode(name):
    try:
        location = geolocator.geocode(name)
        if location:
            return location.latitude, location.longitude
        else:
            return "Not found", "Not found"
    except GeocoderTimedOut:
        time.sleep(1)
        return cached_geocode(name)
    except Exception:
        return "Not found", "Not found"

# Geocode in parallel using threads
def parallel_geocode(institute_list, max_workers=15):
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(cached_geocode, name): name for name in institute_list}
        for i, future in enumerate(as_completed(futures)):
            try:
                result = future.result()
            except Exception:
                result = ("Not found", "Not found")
            results.append(result)
            st.progress((i + 1) / len(institute_list), text=f"Processing {i+1}/{len(institute_list)}")
    return results

# Sidebar mode selection
st.sidebar.header("Choose Input Method")
mode = st.sidebar.radio("Select input type:", ["Manual entry", "Upload file (.csv or .xlsx)"])

# === Manual Input Mode ===
if mode == "Manual entry":
    name = st.text_input("Enter institute name", placeholder="e.g., MIT or IISc Bangalore")
    if st.button("Get Coordinates"):
        if name.strip():
            lat, lon = cached_geocode(name)
            if lat == "Not found":
                st.error("Could not find coordinates.")
            else:
                st.success("Coordinates found!")
                st.write(f"📍 Latitude: **{lat}**, Longitude: **{lon}**")
                st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}))
        else:
            st.warning("Please enter a valid name.")

# === File Upload Mode ===
else:
    uploaded_file = st.file_uploader("Upload CSV or Excel with a column named 'Institute'", type=["csv", "xlsx"])

    if uploaded_file:
        try:
            if uploaded_file.name.endswith(".csv"):
                df = pd.read_csv(uploaded_file)
                file_type = "csv"
            else:
                df = pd.read_excel(uploaded_file)
                file_type = "xlsx"

            if "Institute" not in df.columns:
                st.error("❌ File must contain a column named 'Institute'.")
            else:
                st.info("⏳ Geocoding all institutes. Please wait...")

                names = df["Institute"].astype(str).tolist()
                results = parallel_geocode(names)

                latitudes, longitudes = zip(*results)
                df["Latitude"] = latitudes
                df["Longitude"] = longitudes

                st.success("✅ All geocoding completed.")
                st.dataframe(df)

                # Show map for valid coordinates
                map_df = df[(df["Latitude"] != "Not found") & (df["Longitude"] != "Not found")]
                if not map_df.empty:
                    st.map(map_df.rename(columns={"Latitude": "lat", "Longitude": "lon"}))

                # Download options
                if file_type == "csv":
                    csv_data = df.to_csv(index=False)
                    st.download_button("📤 Download as CSV", csv_data, file_name="institutes_with_coords.csv", mime="text/csv")
                else:
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df.to_excel(writer, index=False, sheet_name="Geocoded Data")
                    st.download_button("📤 Download as Excel", output.getvalue(), file_name="institutes_with_coords.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        except Exception as e:
            st.error(f"❌ Failed to process file: {e}")
