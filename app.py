# app.py
#!/usr/bin/env python3
import os
import io
import time
import re
from flask import Flask, request, render_template_string, send_file
import pandas as pd
import requests
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from dask import delayed, compute
from dask.distributed import Client

# Initialize Dask client for parallel geocoding
# This will use all available threads by default
client = Client(processes=False)

app = Flask(__name__)

# HTML template: simple forms and table
TEMPLATE = '''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Institute Geocoder (Dask Accelerated)</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css"/>
</head>
<body class="p-4">
  <h1>Institute Geocoder (Dask)</h1>
  <form method="post" enctype="multipart/form-data">
    <div class="mb-3">
      <label class="form-label">Upload CSV/XLSX with <code>institute</code> column:</label>
      <input type="file" name="file" accept=".csv,.xls,.xlsx" class="form-control">
    </div>
    <div class="mb-3">
      <label class="form-label">Or paste institutes (one per line or comma-separated):</label>
      <textarea name="text_input" rows="4" class="form-control"></textarea>
    </div>
    <button type="submit" class="btn btn-primary">Geocode</button>
  </form>

  {% if results %}
    <h2 class="mt-4">Results</h2>
    <div class="table-responsive">
      <table class="table table-bordered table-striped">
        <thead><tr><th>Institute</th><th>Latitude</th><th>Longitude</th></tr></thead>
        <tbody>
        {% for inst,lat,lon in results %}
          <tr><td>{{ inst }}</td><td>{{ '%.6f'%lat if lat else '' }}</td><td>{{ '%.6f'%lon if lon else '' }}</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
    <a href="/download/{{ token }}" class="btn btn-success mt-2">Download CSV</a>
  {% endif %}
</body>
</html>'''

# Initialize geocoder
osm = Nominatim(user_agent="InstituteGeocoder/1.0")

# Single geocode: Census API fallback then OSM

def geocode_address(name):
    try:
        resp = requests.get(
            'https://geocoding.geo.census.gov/geocoder/locations/onelineaddress',
            params={'address': f"{name}, USA", 'benchmark': 'Public_AR_Current', 'format': 'json'},
            timeout=5
        )
        data = resp.json()
        match = data.get('result', {}).get('addressMatches', [])
        if match:
            c = match[0]['coordinates']
            return c['y'], c['x']
    except Exception:
        pass
    for _ in range(2):
        try:
            loc = osm.geocode(f"{name}, USA", timeout=10)
            if loc:
                return loc.latitude, loc.longitude
        except (GeocoderTimedOut, GeocoderUnavailable):
            time.sleep(1)
    return None, None

# Split text input

def split_names(text):
    parts = re.split(r'[\r\n,]+', text)
    return [p.strip() for p in parts if p.strip()]

# Batch geocode using Dask

def batch_geocode(names):
    tasks = [delayed(geocode_address)(name) for name in names]
    # Trigger parallel computation
    coords = compute(*tasks, scheduler='threads')
    # coords is a tuple of (lat, lon) per name
    return list(zip(names, coords))

@app.route('/', methods=['GET', 'POST'])
def index():
    results = None
    token = None
    if request.method == 'POST':
        names = []
        f = request.files.get('file')
        if f and f.filename:
            df = (pd.read_excel(f) if f.filename.lower().endswith(('.xls', '.xlsx')) else pd.read_csv(f))
            names = df['institute'].astype(str).tolist()
        text = request.form.get('text_input', '').strip()
        if text:
            names = split_names(text)
        if names:
            results = batch_geocode(names)
            # prepare CSV
            buf = io.StringIO()
            buf.write('institute,latitude,longitude\n')
            for inst, (lat, lon) in results:
                buf.write(f"{inst},{lat or ''},{lon or ''}\n")
            buf.seek(0)
            token = 'tmp'
            app.config[token] = buf.getvalue()
    return render_template_string(TEMPLATE, results=results, token=token)

@app.route('/download/<token>')
def download(token):
    data = app.config.get(token)
    if not data:
        return 'Not found', 404
    return send_file(
        io.BytesIO(data.encode('utf-8')),
        as_attachment=True,
        download_name='geocoded.csv',
        mimetype='text/csv'
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8000)))
