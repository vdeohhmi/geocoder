# app.py
#!/usr/bin/env python3
import os
import io
import time
from flask import Flask, request, render_template_string, send_file
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from concurrent.futures import ThreadPoolExecutor, as_completed

# Simplified HTML template without maps
TEMPLATE = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\">  
  <title>Institute Geocoder</title>
  <link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css\"/>
</head>
<body class=\"p-4\">
  <h1>Institute Geocoder</h1>
  <form method=\"post\" enctype=\"multipart/form-data\" class=\"mb-3\">
    <div class=\"mb-3\">
      <label for=\"file\" class=\"form-label\">Upload CSV/XLSX file with an <code>institute</code> column</label>
      <input type=\"file\" id=\"file\" name=\"file\" accept=\".csv,.xls,.xlsx\" class=\"form-control\" required>
    </div>
    <button type=\"submit\" class=\"btn btn-primary\">Geocode Batch</button>
  </form>

  {% if error %}
    <div class=\"alert alert-danger\">{{ error }}</div>
  {% endif %}

  {% if preview %}
    <h2>Preview</h2>
    {{ preview|safe }}
    <a href=\"{{ download_url }}\" class=\"btn btn-success mt-2\">Download Geocoded File</a>
  {% endif %}
</body>
</html>
"""

# Load concurrency settings from environment
MAX_WORKERS = int(os.getenv('MAX_WORKERS', '50'))
DELAY = float(os.getenv('DELAY', '0.0'))  # seconds between requests

# Initialize geocoder
geolocator = Nominatim(user_agent="InstituteGeocoder/1.0")
app = Flask(__name__)

# Geocode a single institute name with retries

def geocode_name(name, retries=2):
    for _ in range(retries):
        try:
            loc = geolocator.geocode(name, timeout=10)
            if loc:
                return loc.latitude, loc.longitude
        except (GeocoderTimedOut, GeocoderUnavailable):
            time.sleep(1)
    return None, None

# Batch geocode with concurrency
def batch_geocode(names):
    coords = [None] * len(names)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_idx = {executor.submit(geocode_name, name): idx for idx, name in enumerate(names)}
        for future in as_completed(future_to_idx):
            i = future_to_idx[future]
            try:
                coords[i] = future.result()
            except Exception:
                coords[i] = (None, None)
            if DELAY > 0:
                time.sleep(DELAY)
    return coords

@app.route('/', methods=['GET','POST'])
def index():
    if request.method == 'POST':
        f = request.files.get('file')
        if not f:
            return render_template_string(TEMPLATE, error='No file uploaded.', preview=None)
        try:
            df = pd.read_excel(f) if f.filename.lower().endswith(('.xls', '.xlsx')) else pd.read_csv(f)
        except Exception as e:
            return render_template_string(TEMPLATE, error=f'Error reading file: {e}', preview=None)
        if 'institute' not in df.columns:
            return render_template_string(TEMPLATE, error="Missing 'institute' column.", preview=None)

        names = df['institute'].astype(str).tolist()
        coords = batch_geocode(names)
        df[['latitude','longitude']] = pd.DataFrame(coords, index=df.index)

        buf = io.BytesIO()
        base = f.filename.rsplit('.',1)[0]
        if f.filename.lower().endswith(('.xls', '.xlsx')):
            with pd.ExcelWriter(buf, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            download_name = f'{base}_geocoded.xlsx'
        else:
            buf.write(df.to_csv(index=False).encode('utf-8'))
            mimetype = 'text/csv'
            download_name = f'{base}_geocoded.csv'
        buf.seek(0)

        token = f'{base}_token'
        app.config[token] = (buf, download_name, mimetype)
        preview = df.head().to_html(classes='table table-striped', index=False)
        return render_template_string(TEMPLATE, error=None, preview=preview, download_url=f'/download/{token}')

    return render_template_string(TEMPLATE, error=None, preview=None)

@app.route('/download/<token>')
def download(token):
    entry = app.config.get(token)
    if not entry:
        return 'Invalid token', 404
    buf, filename, mimetype = entry
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=filename, mimetype=mimetype)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8000)))
