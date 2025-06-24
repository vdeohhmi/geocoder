# 1️⃣ Install dependencies (run once)
!pip install geopy folium pandas ipywidgets
!jupyter nbextension enable --py widgetsnbextension

# 2️⃣ Imports
from geopy.geocoders import Nominatim
import pandas as pd
import folium
from ipywidgets import Text, Button, Dropdown, Output, FileUpload, VBox, HBox
from IPython.display import display, clear_output
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.colab import files
import io, urllib.parse, urllib.request, json

# 3️⃣ Geocoding helpers
geolocator = Nominatim(user_agent="ColabInstituteLocator/1.0")

def fetch_json(params):
    url = f"https://nominatim.openstreetmap.org/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": geolocator.headers['User-Agent']})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())

def get_suggestions(query, limit=10):
    params = {"q": query, "format": "json", "limit": limit, "addressdetails": 0}
    try:
        return fetch_json(params)
    except:
        return []

def filter_unis(results, query):
    uni_matches = [
        r for r in results
        if "university" in r.get("display_name","").lower() 
           and query.lower() in r["display_name"].lower()
    ]
    if uni_matches: return uni_matches
    type_matches = [r for r in results if r.get("type")=="university"]
    return type_matches or results

# 4️⃣ Widgets
query_in = Text(placeholder="e.g. Temple or MIT", description="Search:")
search_btn = Button(description="🔍 Find")
suggest_dd = Dropdown(options=[], description="Choose:")
map_out    = Output()
batch_upl  = FileUpload(accept=".csv,.xlsx", multiple=False, description="Batch Upload")
batch_out  = Output()

# 5️⃣ Single‐lookup flow
def on_search(_):
    map_out.clear_output()
    raw = get_suggestions(query_in.value, limit=10)
    choices = filter_unis(raw, query_in.value)
    suggest_dd.options = [(c["display_name"], c) for c in choices]

search_btn.on_click(on_search)

def on_pick(change):
    if not change.new: return
    sel = change.new
    lat, lon = float(sel["lat"]), float(sel["lon"])
    map_out.clear_output()
    with map_out:
        print(f"🏫 {sel['display_name']}\nLatitude: {lat:.6f}\nLongitude: {lon:.6f}")
        m = folium.Map(location=[lat,lon], zoom_start=15)
        folium.Marker([lat,lon], tooltip=sel['display_name']).add_to(m)
        display(m)

suggest_dd.observe(on_pick, names="value")

# 6️⃣ Batch‐mode flow
def on_upload(change):
    batch_out.clear_output()
    uploaded = change.new
    if not uploaded: return
    # read file
    key = list(uploaded.keys())[0]
    content = uploaded[key]['content']
    df = (
        pd.read_excel(io.BytesIO(content)) 
        if key.lower().endswith(("xls","xlsx")) 
        else pd.read_csv(io.BytesIO(content))
    )
    if "institute" not in df.columns:
        with batch_out: print("🔴 Your file needs an ‘institute’ column.")
        return
    
    with batch_out:
        print(f"Processing {len(df)} rows…")
    # geocode in parallel
    results = {}
    def worker(idx, name):
        res = get_suggestions(name, limit=5)
        filt = filter_unis(res, name)
        if filt:
            return idx, (float(filt[0]["lat"]), float(filt[0]["lon"]))
        return idx, (None,None)
    
    with ThreadPoolExecutor(max_workers=8) as exe:
        futures = [exe.submit(worker,i,name) for i,name in enumerate(df["institute"].astype(str))]
        for fut in as_completed(futures):
            i,(lat,lon) = fut.result()
            results[i] = (lat,lon)
    
    df["latitude"]  = df.index.map(lambda i: results[i][0])
    df["longitude"] = df.index.map(lambda i: results[i][1])
    
    with batch_out:
        display(df.head())
        # download links
        buf = io.BytesIO()
        df.to_csv(buf, index=False)
        files.download(buf.getvalue(), "geocoded_institutes.csv")

batch_upl.observe(on_upload, names="value")

# 7️⃣ Layout
single_box = VBox([HBox([query_in, search_btn]), suggest_dd, map_out])
batch_box  = VBox([batch_upl, batch_out])

display(VBox([single_box, batch_box]))
