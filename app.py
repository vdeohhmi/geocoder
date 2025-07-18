# app.py
#!/usr/bin/env python3
import os
import io
import time
import re
from flask import Flask, request, render_template_string, send_file
import pandas as pd
from geopy.geocoders import ArcGIS, Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# Configure geocoders
arcgis = ArcGIS(timeout=10)
osm = Nominatim(user_agent="InstituteGeocoder/1.0")

# HTML template with upload/text, inline results, and download link
TEMPLATE = '''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Institute Geocoder</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css"/>
</head>
<body class="p-4">
  <h1>Institute Geocoder</h1>
  <form method="post" enctype="multipart/form-data">
    <div class="mb-3">
      <label class="form-label">CSV/XLSX with <code>institute</code> column:</label>
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
      <table class="table table-bordered">
        <thead><tr><th>Institute</th><th>Latitude</th><th>Longitude</th></tr></thead>
        <tbody>
          {% for inst, lat, lon in results %}
            <tr>
              <td>{{ inst }}</td>
              <td>{{ '%.6f'|format(lat) if lat is not none else '' }}</td>
              <td>{{ '%.6f'|format(lon) if lon is not none else '' }}</td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    <a href="/download/{{ token }}" class="btn btn-success mt-2">Download CSV</a>
  {% endif %}
</body>
</html>'''

# Geocode a single name using ArcGIS first, then Nominatim fallback

def geocode_name(name):
    try:
        loc = arcgis.geocode(name, exactly_one=True)
        if loc:
            return loc.latitude, loc.longitude
    except GeocoderServiceError:
        pass
    for _ in range(2):
        try:
            loc = osm.geocode(name, exactly_one=True)
            if loc:
                return loc.latitude, loc.longitude
            loc = osm.geocode(f"{name}, USA", exactly_one=True)
            if loc:
                return loc.latitude, loc.longitude
        except (GeocoderTimedOut, GeocoderServiceError):
            time.sleep(1)
    return None, None

# Split text preserving parentheses

def split_names(text):
    names = []
    for line in text.splitlines():
        buf, depth = '', 0
        for ch in line:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth = max(depth-1, 0)
            if ch == ',' and depth == 0:
                if buf.strip(): names.append(buf.strip())
                buf = ''
            else:
                buf += ch
        if buf.strip(): names.append(buf.strip())
    return names

# Batch geocode concurrently, preserve input order

def batch_geocode(names, workers=10):
    futures = []
    with ThreadPoolExecutor(max_workers=workers) as exe:
        for n in names:
            futures.append((n, exe.submit(geocode_name, n)))
    results = []
    for name, fut in futures:
        try:
            lat, lon = fut.result()
        except:
            lat, lon = None, None
        results.append((name, lat, lon))
    return results

@app.route('/', methods=['GET', 'POST'])
def index():
    results = None
    token = None
    if request.method == 'POST':
        names = []
        f = request.files.get('file')
        if f and f.filename:
            try:
                df = pd.read_excel(f) if f.filename.lower().endswith(('.xls', '.xlsx')) else pd.read_csv(f)
                names = df['institute'].astype(str).tolist()
            except:
                names = []
        if not names:
            text = request.form.get('text_input', '')
            names = split_names(text)
        if names:
            results = batch_geocode(names)
            buf = io.StringIO()
            buf.write('institute,latitude,longitude\n')
            for inst, lat, lon in results:
                buf.write(f"{inst},{lat or ''},{lon or ''}\n")
            buf.seek(0)
            token = 'r'
            app.config[token] = buf.getvalue()
    return render_template_string(TEMPLATE, results=results, token=token)

@app.route('/download/<token>')
def download(token):
    data = app.config.get(token)
    if not data:
        return 'Not found', 404
    return send_file(
        io.BytesIO(data.encode()),
        as_attachment=True,
        download_name='geocoded.csv',
        mimetype='text/csv'
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8000)))
