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
<title>Batch Institute Geocoder</title>
<h1>🏫 Batch Institute Geocoder</h1>
{% if error %}
  <p style="color:red;">⚠️ {{ error }}</p>
{% endif %}
<form method="post" enctype="multipart/form-data">
  <label>Upload CSV or Excel (with column “institute”):</label><br/>
  <input type="file" name="file" accept=".csv,.xls,.xlsx" required>
  <button type="submit">Upload & Geocode</button>
</form>

{% if preview %}
  <h2>Preview (first 5 rows)</h2>
  {{ preview|safe }}
  <p><a href="{{ download_url }}">📥 Download full geocoded file</a></p>
{% endif %}
"""

def geocode_name(name: str):
    try:
        loc = geolocator.geocode(name, timeout=10)
        if loc:
            return loc.latitude, loc.longitude
    except GeocoderTimedOut:
        pass
    return None, None

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        upload = request.files.get("file")
        if not upload:
            return render_template_string(TEMPLATE, error="No file uploaded.", preview=None)
        try:
            if upload.filename.lower().endswith((".xls", ".xlsx")):
                df = pd.read_excel(upload)
            else:
                df = pd.read_csv(upload)
        except Exception as e:
            return render_template_string(TEMPLATE, error=f"File read error: {e}", preview=None)
        if "institute" not in df.columns:
            return render_template_string(TEMPLATE, error="Missing column `institute`.", preview=None)
        coords = df["institute"].astype(str).apply(geocode_name)
        df[["latitude", "longitude"]] = pd.DataFrame(coords.tolist(), index=df.index)
        buf = io.BytesIO()
        fname = upload.filename.rsplit(".", 1)[0]
        if upload.filename.lower().endswith((".xls", ".xlsx")):
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df.to_excel(writer, index=False)
            mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            download_name = f"{fname}_geocoded.xlsx"
        else:
            buf.write(df.to_csv(index=False).encode("utf-8"))
            mimetype = "text/csv"
            download_name = f"{fname}_geocoded.csv"
        buf.seek(0)
        token = upload.filename + "_token"
        app.config[token] = (buf, download_name, mimetype)
        preview_html = df.head().to_html(classes="table table-striped", index=False)
        download_url = f"/download/{token}"
        return render_template_string(TEMPLATE, error=None, preview=preview_html, download_url=download_url)
    return render_template_string(TEMPLATE, error=None, preview=None)

@app.route("/download/<token>")
def download(token):
    entry = app.config.get(token)
    if not entry:
        return "Invalid download token.", 404
    buf, filename, mimetype = entry
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=filename, mimetype=mimetype)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
