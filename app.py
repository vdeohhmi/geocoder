# app.py
#!/usr/bin/env python3
import os
import io
import time
import re
from flask import Flask, request, render_template_string, send_file
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from concurrent.futures import ThreadPoolExecutor, as_completed

# HTML template with two forms: file upload and free-text input
TEMPLATE = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\">  
  <title>Institute Geocoder</title>
  <link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css\"/>
</head>
<body class=\"p-4\">
  <h1>Institute Geocoder</h1>

  <h2>Batch Upload</h2>
  <form method=\"post\" enctype=\"multipart/form-data\" class=\"mb-4\">
    <div class=\"mb-3\">
      <label for=\"file\" class=\"form-label\">Upload CSV/XLSX with <code>institute</code> column:</label>
      <input type=\"file\" id=\"file\" name=\"file\" accept=\".csv,.xls,.xlsx\" class=\"form-control\">
    </div>
    <button name=\"action\" value=\"geocode_file\" type=\"submit\" class=\"btn btn-primary\">Geocode File</button>
  </form>

  <h2>Free Text Geocoding</h2>
  <form method=\"post\" class=\"mb-4\">
    <div class=\"mb-3\">
      <label for=\"text_input\" class=\"form-label\">Paste institute names (one per line or comma-separated):</label>
      <textarea id=\"text_input\" name=\"text_input\" rows=6 class=\"form-control\"></textarea>
    </div>
    <button name=\"action\" value=\"geocode_text\" type=\"submit\" class=\"btn btn-secondary\">Geocode Text</button>
  </form>

  {% if error %}
    <div class=\"alert alert-danger\">{{ error }}</div>
  {% endif %}

  {% if preview %}
    <h2>Results</h2>
    {{ preview|safe }}
    {% if download_url %}
      <a href=\"{{ download_url }}\" class=\"btn btn-success mt-2\">Download Geocoded File</a>
    {% endif %}
  {% endif %}
</body>
</html>
"""

# Concurrency settings
MAX_WORKERS = int(os.getenv('MAX_WORKERS', '50'))
DELAY = float(os.getenv('DELAY', '0.0'))

# Initialize
app = Flask(__name__)
geolocator = Nominatim(user_agent="InstituteGeocoder/1.0")

# Single geocode with retry
def geocode_name(name, retries=2):
    for _ in range(retries):
        try:
            loc = geolocator.geocode(name, timeout=10)
            if loc:
                return loc.latitude, loc.longitude
        except (GeocoderTimedOut, GeocoderUnavailable):
            time.sleep(1)
    return None, None

# Batch geocode list of names
def batch_geocode(names):
    coords = [None] * len(names)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_idx = {executor.submit(geocode_name, n): i for i, n in enumerate(names)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                coords[idx] = future.result()
            except Exception:
                coords[idx] = (None, None)
            if DELAY:
                time.sleep(DELAY)
    return coords

@app.route('/', methods=['GET','POST'])
def index():
    error = None
    preview = None
    download_url = None

    if request.method == 'POST':
        action = request.form.get('action')

        # File geocoding
        if action == 'geocode_file' and 'file' in request.files:
            f = request.files['file']
            if not f or not f.filename:
                error = 'No file selected.'
            else:
                try:
                    df = pd.read_excel(f) if f.filename.lower().endswith(('.xls', '.xlsx')) else pd.read_csv(f)
                except Exception as e:
                    error = f'Error reading file: {e}'
                    df = None
                if df is not None:
                    if 'institute' not in df.columns:
                        error = "Missing 'institute' column."
                    else:
                        names = df['institute'].astype(str).tolist()
                        coords = batch_geocode(names)
                        df[['latitude','longitude']] = pd.DataFrame(coords, index=df.index)
                        buf = io.BytesIO()
                        base = f.filename.rsplit('.',1)[0]
                        if f.filename.lower().endswith(('.xls', '.xlsx')):
                            with pd.ExcelWriter(buf, engine='openpyxl') as w: df.to_excel(w, index=False)
                            mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                            fname = f'{base}_geocoded.xlsx'
                        else:
                            buf.write(df.to_csv(index=False).encode('utf-8'))
                            mimetype = 'text/csv'
                            fname = f'{base}_geocoded.csv'
                        buf.seek(0)
                        token = f'{base}_token'
                        app.config[token] = (buf, fname, mimetype)
                        preview = df.head().to_html(classes='table table-striped', index=False)
                        download_url = f'/download/{token}'

        # Text geocoding
        elif action == 'geocode_text':
            text = request.form.get('text_input', '')
            if not text.strip():
                error = 'No text provided.'
            else:
                parts = re.split(r'[\r\n,]+', text)
                names = [p.strip() for p in parts if p.strip()]
                coords = batch_geocode(names)
                result_df = pd.DataFrame({
                    'institute': names,
                    'latitude': [c[0] for c in coords],
                    'longitude': [c[1] for c in coords]
                })
                preview = result_df.to_html(classes='table table-striped', index=False)

    return render_template_string(TEMPLATE, error=error, preview=preview, download_url=download_url)

@app.route('/download/<token>')
def download(token):
    data = app.config.get(token)
    if not data:
        return 'Invalid token', 404
    buf, fname, mimetype = data
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=fname, mimetype=mimetype)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8000)
