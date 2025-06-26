# app.py
#!/usr/bin/env python3
import os
import io
import time
import re
from flask import Flask, request, render_template_string, send_file
import pandas as pd
from geopy.geocoders import GoogleV3
from geopy.exc import GeocoderTimedOut, GeocoderQuotaExceeded
from concurrent.futures import ThreadPoolExecutor, as_completed

# HTML template with batch upload and free-text geocoding
TEMPLATE = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\">  
  <title>Institute Geocoder</title>
  <link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css\"/>
</head>
<body class=\"p-4\">
  <h1>Institute Geocoder</h1>
  <p class=\"text-muted\">Powered by Google Geocoding API</p>

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
tasks = int(os.getenv('MAX_WORKERS', '10'))

# Initialize Flask app and Google geocoder
API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
if not API_KEY:
    raise RuntimeError('Please set GOOGLE_MAPS_API_KEY environment variable')

geo = GoogleV3(api_key=API_KEY, timeout=10)
app = Flask(__name__)

# Geocode helper with retries
async def geocode_name(name, retries=2):
    try:
        return geo.geocode(name)
    except GeocoderQuotaExceeded:
        return None
    except GeocoderTimedOut:
        if retries > 0:
            time.sleep(1)
            return geocode_name(name, retries-1)
        return None

# Batch geocode using ThreadPoolExecutor
from functools import partial

def batch_geocode(names):
    results = []
    with ThreadPoolExecutor(max_workers=tasks) as executor:
        futures = {executor.submit(geocode_name, n): n for n in names}
        for future in as_completed(futures):
            name = futures[future]
            try:
                loc = future.result()
                if loc:
                    results.append((loc.latitude, loc.longitude))
                else:
                    results.append((None, None))
            except Exception:
                results.append((None, None))
    return results

@app.route('/', methods=['GET','POST'])
def index():
    error = None
    preview = None
    download_url = None

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'geocode_file' and 'file' in request.files:
            f = request.files['file']
            if not f.filename:
                error = 'No file selected.'
            else:
                try:
                    df = pd.read_excel(f) if f.filename.lower().endswith(('.xls','.xlsx')) else pd.read_csv(f)
                except Exception as e:
                    error = f'Error reading file: {e}'
                    df = None
                if df is not None:
                    if 'institute' not in df.columns:
                        error = "Missing 'institute' column."
                    else:
                        coords = batch_geocode(df['institute'].astype(str).tolist())
                        df[['latitude','longitude']] = pd.DataFrame(coords)
                        buf = io.BytesIO()
                        base = os.path.splitext(f.filename)[0]
                        if f.filename.lower().endswith(('.xls','.xlsx')):
                            df.to_excel(buf, index=False)
                            mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                            fname = f'{base}_geocoded.xlsx'
                        else:
                            buf.write(df.to_csv(index=False).encode())
                            mimetype = 'text/csv'
                            fname = f'{base}_geocoded.csv'
                        buf.seek(0)
                        token = base + '_token'
                        app.config[token] = (buf, fname, mimetype)
                        preview = df.head().to_html(classes='table table-striped', index=False)
                        download_url = f'/download/{token}'

        elif action == 'geocode_text':
            text = request.form.get('text_input', '')
            if not text.strip():
                error = 'No text provided.'
            else:
                names = [n.strip() for n in re.split(r'[\r\n,]+', text) if n.strip()]
                coords = batch_geocode(names)
                df = pd.DataFrame({'institute': names,
                                   'latitude': [c[0] for c in coords],
                                   'longitude': [c[1] for c in coords]})
                preview = df.to_html(classes='table table-striped', index=False)

    return render_template_string(TEMPLATE, error=error, preview=preview, download_url=download_url)

@app.route('/download/<token>')
def download(token):
    entry = app.config.get(token)
    if not entry:
        return 'Invalid token', 404
    buf, fname, mimetype = entry
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=fname, mimetype=mimetype)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
