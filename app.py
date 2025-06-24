#!/usr/bin/env python3
from flask import Flask, request, render_template_string, send_file
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import io

app = Flask(__name__)
geolocator = Nominatim(user_agent="InstituteGeocoder/1.0")

TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Institute Geocoder</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet-control-geocoder/dist/Control.Geocoder.css"/>
  <style>#mapid,#batchmap{height:400px;margin-bottom:1em;}</style>
</head>
<body>
<h1>Institute Geocoder</h1>
<div id="mapid"></div>
<p id="coords">Search above to see coordinates.</p>
<form method="post" enctype="multipart/form-data">
  <input type="file" name="file" accept=".csv,.xls,.xlsx" required>
  <button type="submit">Upload & Geocode Batch</button>
</form>
{% if error %}<p style="color:red">{{error}}</p>{% endif %}
{% if preview %}
<h2>Preview</h2>{{preview|safe}}
<p><a href="{{download_url}}">Download Geocoded File</a></p>
<div id="batchmap"></div>
{% endif %}
<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet-control-geocoder/dist/Control.Geocoder.js"></script>
<script>
var map=L.map('mapid').setView([20,0],2);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap'}).addTo(map);
L.Control.geocoder({defaultMarkGeocode:false})
  .on('markgeocode',function(e){
    var latlng=e.geocode.center;
    L.marker(latlng).addTo(map);
    map.setView(latlng,13);
    document.getElementById('coords').textContent='Latitude: '+latlng.lat.toFixed(6)+', Longitude: '+latlng.lng.toFixed(6);
  }).addTo(map);
{% if batch_coords %}
var bm=L.map('batchmap').setView([0,0],2);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap'}).addTo(bm);
var coords={{batch_coords|tojson}};
var bounds=[];
coords.forEach(function(c){
  if(c[0]&&c[1]){
    L.marker(c).addTo(bm);
    bounds.push(c);
  }
});
if(bounds.length) bm.fitBounds(bounds);
{% endif %}
</script>
</body>
</html>
"""

def geocode_name(name:str):
    try:
        loc=geolocator.geocode(name,timeout=10)
        if loc: return loc.latitude,loc.longitude
    except GeocoderTimedOut: pass
    return None,None

@app.route("/",methods=["GET","POST"])
def index():
    if request.method=="POST":
        f=request.files.get("file")
        if not f: return render_template_string(TEMPLATE,error="No file.",preview=None)
        try:
            df=pd.read_excel(f) if f.filename.lower().endswith(("xls","xlsx")) else pd.read_csv(f)
        except Exception as e:
            return render_template_string(TEMPLATE,error=str(e),preview=None)
        if "institute" not in df.columns:
            return render_template_string(TEMPLATE,error="Missing institute column.",preview=None)
        coords=df["institute"].astype(str).apply(geocode_name)
        df[["latitude","longitude"]]=pd.DataFrame(coords.tolist(),index=df.index)
        buf=io.BytesIO();name=f.filename.rsplit(".",1)[0]
        if f.filename.lower().endswith(("xls","xlsx")):
            with pd.ExcelWriter(buf,engine="openpyxl") as w: df.to_excel(w,index=False)
            mt="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";dl=name+"_geocoded.xlsx"
        else:
            buf.write(df.to_csv(index=False).encode());mt="text/csv";dl=name+"_geocoded.csv"
        buf.seek(0);token=f.filename+"_token";app.config[token]=(buf,dl,mt)
        preview=df.head().to_html(classes="table table-striped",index=False)
        coords_list=[list(t) for t in coords.tolist()]
        return render_template_string(TEMPLATE,error=None,preview=preview,download_url="/download/"+token,batch_coords=coords_list)
    return render_template_string(TEMPLATE,error=None,preview=None,batch_coords=None)

@app.route("/download/<token>")
def download(token):
    entry=app.config.get(token)
    if not entry: return "Invalid token",404
    buf,fn,mt=entry;buf.seek(0)
    return send_file(buf,as_attachment=True,download_name=fn,mimetype=mt)

if __name__=="__main__":
    app.run(host="0.0.0.0",port=8000)
