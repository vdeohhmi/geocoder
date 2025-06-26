# app.py
#!/usr/bin/env python3
import os
import io
import time
import re
from flask import Flask, request, render_template_string, send_file
import pandas as pd
from geopy.geocoders import ArcGIS
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from concurrent.futures import ThreadPoolExecutor, as_completed

# HTML template with manual table rendering for perfect alignment
TEMPLATE = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\">  
  <title>Institute Geocoder</title>
  <link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css\"/>
</head>
<body class=\"p-4\">
  <h1>Institute Geocoder</h1>
  <p class=\"text-muted\">Powered by ArcGIS Public Geocoder (no API key required)</p>

  <h2>Batch Upload</h2>
  <form method=\"post\" enctype=\"multipart/form-data\" class=\"mb-4\">
    <div class=\"mb-3\">
      <label for=\"file\" class=\"form-label\">Upload CSV/XLSX with <code>institute</code> column:</label>
      <input type=\"file\" id=\"file\" name=\"file\" accept=\".csv,.xls,.xlsx\" class=\"form-control\" required>
    </div>
    <button name=\"action\" value=\"geocode_file\" type=\"submit\" class=\"btn btn-primary\">Geocode File</button>
  </form>

  <h2>Free Text Geocoding</h2>
  <form method=\"post\" class=\"mb-4\">
    <div class=\"mb-3\">
      <label for=\"text_input\" class=\"form-label\">Paste institute names (one per line or comma-separated):</label>
      <textarea id=\"text_input\" name=\"text_input\" rows=6 class=\"form-control\" required></textarea>
    </div>
    <button name=\"action\" value=\"geocode_text\" type=\"submit\" class=\"btn btn-secondary\">Geocode Text</button>
  </form>

  {% if error %}
    <div class=\"alert alert-danger\">{{ error }}</div>
  {% endif %}

  {% if results %}
    <h2>Results</h2>
    <div class=\"table-responsive\">
      <table class=\"table table-striped\">
        <thead>
          <tr>
            <th>Institute</th>
            <th>Latitude</th>
            <th>Longitude</th>
          </tr>
        </thead>
        <tbody>
          {% for r in results %}
          <tr>
            <td>{{ r.institute }}</td>
            <td>{{ '%.6f'|format(r.latitude) if r.latitude is not none else '' }}</td>
            <td>{{ '%.6f'|format(r.longitude) if r.longitude is not none else '' }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% if download_url %}
      <a href=\"{{ download_url }}\" class=\"btn btn-success mt-2\">Download Geocoded File</a>
    {% endif %}
  {% endif %}
</body>
</html>
"""

# Throttle settings
MAX_WORKERS = int(os.getenv('MAX_WORKERS', '5'))
DELAY = float(os.getenv('DELAY', '0.2'))

# Initialize Flask and geocoder
app = Flask(__name__)
geolocator = ArcGIS(timeout=10)

# Geocode with retries
def geocode_name(name, retries=2):
    for _ in range(retries + 1):
        try:
            loc = geolocator.geocode(name)
            if loc:
                return loc.latitude, loc.longitude
        except (GeocoderTimedOut, GeocoderServiceError):
            time.sleep(1)
    return None, None

# Batch geocode names
def batch_geocode(names):
    coords = [None] * len(names)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {executor.submit(geocode_name, n): i for i, n in enumerate(names)}
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                coords[idx] = future.result()
            except Exception:
                coords[idx] = (None, None)
            time.sleep(DELAY)
    return coords

@app.route('/', methods=['GET','POST'])
def index():
    error = None
    results = []
    download_url = None

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'geocode_file' and 'file' in request.files:
            f = request.files['file']
            if not f.filename:
                error = 'No file selected.'
            else:
                try:
                    df = (pd.read_excel(f) if f.filename.lower().endswith(('.xls','.xlsx'))
                          else pd.read_csv(f))
                except Exception as e:
                    error = f'Error reading file: {e}'
                    df = None
                if df is not None:
                    if 'institute' not in df.columns:
                        error = "Missing 'institute' column."
                    else:
                        names = df['institute'].astype(str).tolist()
                        coords = batch_geocode(names)
                        # build results list
                        results = [
                            {'institute': n, 'latitude': c[0], 'longitude': c[1]}
                            for n, c in zip(names, coords)
                        ]
                        # prepare download
                        df['latitude'], df['longitude'] = zip(*coords)
                        buf = io.BytesIO()
                        base = os.path.splitext(f.filename)[0]
                        if f.filename.lower().endswith(('.xls','.xlsx')):
                            df.to_excel(buf, index=False)
                            mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                            fname = f'{base}_geocoded.xlsx'
                        else:
                            buf.write(df.to_csv(index=False).encode('utf-8'))
                            mimetype = 'text/csv'
                            fname = f'{base}_geocoded.csv'
                        buf.seek(0)
                        token = base + '_token'
                        app.config[token] = (buf, fname, mimetype)
                        download_url = f'/download/{token}'

        elif action == 'geocode_text':
            text = request.form.get('text_input', '')
            if not text.strip():
                error = 'No text provided.'
            else:
                names = [p.strip() for p in re.split(r'[\r\n,]+', text) if p.strip()]
                coords = batch_geocode(names)
                results = [
                    {'institute': n, 'latitude': c[0], 'longitude': c[1]}
                    for n, c in zip(names, coords)
                ]

    return render_template_string(TEMPLATE, error=error, results=results, download_url=download_url)

@app.route('/download/<token>')
def download(token):
    entry = app.config.get(token)
    if not entry:
        return 'Invalid token', 404
    buf, fname, mimetype = entry
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=fname, mimetype=mimetype)

if __name__ == '__main__':
    port = int(os.getenv('PORT', '8000'))
    app.run(host='0.0.0.0', port=port)
