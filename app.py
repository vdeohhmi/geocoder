# app.py
#!/usr/bin/env python3
import os
import io
import time
import re
from flask import Flask, request, render_template_string, send_file
import pandas as pd

# Try Geocodio first, fallback to Nominatim
try:
    from geocodio import GeocodioClient
    GEOCODIO_KEY = os.getenv('GEOCODIO_API_KEY')
    geocodio = GeocodioClient(api_key=GEOCODIO_KEY) if GEOCODIO_KEY else None
except ImportError:
    geocodio = None

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable

# HTML template with batch & free-text forms and manual rendering for alignment
TEMPLATE = """<!doctype html>
<html><head>
  <meta charset=\"utf-8\">  
  <title>Institute Geocoder</title>
  <link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css\"/>
</head><body class=\"p-4\">
  <h1>Institute Geocoder</h1>
  {% if geocodio %}
    <p class=\"text-info\">Using Geocodio batch geocoding (fast, accurate)</p>
  {% else %}
    <p class=\"text-warning\">Using Nominatim (rate-limited, U.S.-biased)</p>
  {% endif %}

  <h2>Batch Upload</h2>
  <form method=\"post\" enctype=\"multipart/form-data\" class=\"mb-4\">
    <div class=\"mb-3\">
      <label class=\"form-label\">CSV/XLSX with <code>institute</code> column:</label>
      <input type=\"file\" name=\"file\" accept=\".csv,.xls,.xlsx\" class=\"form-control\" required>
    </div>
    <button name=\"action\" value=\"geocode_file\" class=\"btn btn-primary\">Geocode File</button>
  </form>

  <h2>Free Text Geocoding</h2>
  <form method=\"post\" class=\"mb-4\">
    <div class=\"mb-3\">
      <label class=\"form-label\">Paste institutes (one per line or comma-separated):</label>
      <textarea name=\"text_input\" rows=6 class=\"form-control\" required></textarea>
    </div>
    <button name=\"action\" value=\"geocode_text\" class=\"btn btn-secondary\">Geocode Text</button>
  </form>

  {% if error %}<div class=\"alert alert-danger\">{{ error }}</div>{% endif %}

  {% if results %}
  <h2>Results</h2>
  <div class=\"table-responsive\">
    <table class=\"table table-bordered table-striped\">
      <thead><tr><th>Institute</th><th>Latitude</th><th>Longitude</th></tr></thead>
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
  {% if download_url %}<a href=\"{{ download_url }}\" class=\"btn btn-success mt-2\">Download Geocoded File</a>{% endif %}
  {% endif %}
</body></html>
"""

app = Flask(__name__)
# fallback geocoder
osm = Nominatim(user_agent="InstituteGeocoder/1.0")

def split_names(text):
    # split on commas only at depth=0
    names, buf, depth = [], '', 0
    for ch in text:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth = max(depth-1, 0)
        if ch == ',' and depth == 0:
            names.append(buf.strip())
            buf = ''
        else:
            buf += ch
    if buf.strip(): names.append(buf.strip())
    return names

def geocode_batch_geocodio(names):
    # uses geocodio batch
    resp = geocodio.geocode(names)
    coords = []
    for r in resp:
        loc = r.get('location')
        coords.append((loc['lat'], loc['lng']) if loc else (None, None))
    return coords

# geocode single via OSM
import time
from geopy.exc import GeocoderTimedOut

def geocode_osm(name):
    for _ in range(3):
        try:
            loc = osm.geocode(f"{name}, USA", timeout=10)
            if loc: return loc.latitude, loc.longitude
        except GeocoderTimedOut:
            time.sleep(1)
    return None, None

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
                error = 'No file.'
            else:
                try:
                    df = pd.read_excel(f) if f.filename.lower().endswith(('.xls','.xlsx')) else pd.read_csv(f)
                except Exception as e:
                    error = f'File read error: {e}'
                    df = None
                if df is not None:
                    if 'institute' not in df.columns:
                        error = "Missing 'institute'."
                    else:
                        names = df['institute'].astype(str).tolist()
                        if geocodio:
                            coords = geocode_batch_geocodio(names)
                        else:
                            coords = [geocode_osm(n) for n in names]
                        df['latitude'], df['longitude'] = zip(*coords)
                        results = [{'institute': n, 'latitude': c[0], 'longitude': c[1]} for n, c in zip(names, coords)]
                        # prepare download
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
            text = request.form.get('text_input','')
            if not text.strip(): error='No input.'
            else:
                names = []
                for line in text.splitlines():
                    names.extend(split_names(line))
                coords = geocode_batch_geocodio(names) if geocodio else [geocode_osm(n) for n in names]
                results = [{'institute': n, 'latitude': c[0], 'longitude': c[1]} for n,c in zip(names, coords)]
    return render_template_string(TEMPLATE, error=error, results=results, download_url=download_url, geocodio=bool(geocodio))

@app.route('/download/<token>')
def download(token):
    entry = app.config.get(token)
    if not entry: return 'Invalid',404
    buf, fname, mimetype = entry
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=fname, mimetype=mimetype)

if __name__=='__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT',8000)))
