import streamlit as st
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import pandas as pd
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import io

st.set_page_config(page_title="Institute Geolocation Finder", layout="wide")
st.title("🏫 Institute Geolocation Finder")

geolocator = Nominatim(user_agent="GeoLocatorApp", timeout=10)

@st.cache_data(show_spinner=False)
def cached_geocode(name):
    try:
        loc = geolocator.geocode(name)
        if loc:
            return loc.latitude, loc.longitude
        return "Not found", "Not found"
    except GeocoderTimedOut:
        time.sleep(1)
        return cached_geocode(name)
    except:
        return "Not found", "Not found"

def parallel_geocode(names, max_workers=15):
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(cached_geocode, n): n for n in names}
        for i, fut in enumerate(as_completed(futures)):
            try:
                results.append(fut.result())
            except:
                results.append(("Not found", "Not found"))
            st.progress((i+1)/len(names), text=f"Processing {i+1}/{len(names)}")
    return results

mode = st.sidebar.radio("Select input type:", ["Manual entry", "Upload file (.csv or .xlsx)"])

if mode == "Manual entry":
    name = st.text_input("Enter institute name", placeholder="e.g., MIT or IISc Bangalore")
    if st.button("Get Coordinates") and name.strip():
        lat, lon = cached_geocode(name)
        if lat == "Not found":
            st.error("Could not find coordinates.")
        else:
            st.success("Coordinates found!")
            st.write(f"📍 Latitude: **{lat}**, Longitude: **{lon}**")
            st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}))
    elif st.button("Get Coordinates"):
        st.warning("Please enter a valid name.")
else:
    uploaded = st.file_uploader("Upload CSV or Excel with a column named 'Institute'", type=["csv", "xlsx"])
    if uploaded:
        try:
            df = pd.read_csv(uploaded) if uploaded.name.endswith(".csv") else pd.read_excel(uploaded)
            if "Institute" not in df.columns:
                st.error("❌ File must contain a column named 'Institute'.")
            else:
                st.info("⏳ Geocoding all institutes. Please wait...")
                names = df["Institute"].astype(str).tolist()
                coords = parallel_geocode(names)
                df["Latitude"], df["Longitude"] = zip(*coords)
                st.success("✅ All geocoding completed.")
                st.dataframe(df)
                valid = df[(df["Latitude"]!="Not found")&(df["Longitude"]!="Not found")]
                if not valid.empty:
                    st.map(valid.rename(columns={"Latitude":"lat","Longitude":"lon"}))
                if uploaded.name.endswith(".csv"):
                    st.download_button("📤 Download CSV", df.to_csv(index=False), "institutes_with_coords.csv", "text/csv")
                else:
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine="openpyxl") as w:
                        df.to_excel(w, index=False, sheet_name="Geocoded Data")
                    st.download_button("📤 Download Excel", buf.getvalue(), "institutes_with_coords.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e:
            st.error(f"❌ Failed to process file: {e}")







