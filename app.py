# app.py
#!/usr/bin/env python3
import os
import io
import time
import re
import uuid
from threading import Thread
from flask import Flask, request, render_template_string, send_file
import pandas as pd
import requests
from geopy.geocoders import ArcGIS, Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from concurrent.futures import ThreadPoolExecutor, as_completed

# Initialize Flask and in-memory job store
app = Flask(__name__)
jobs = {}  # job_id -> {'status': 'pending'|'done', 'results': list, 'csv': str}

# Configure geocoders
arcgis = ArcGIS(timeout=10)
osm = Nominatim(user_agent="InstituteGeocoder/1.0")

# HTML template for submission, status, results, and download
TEMPLATE = '''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Institute Geocoder</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css"/>
</head>
<body class="p-4">
  <h1>Institute Geocoder</h1>
  {% if not job_id %}
    <form method="post" enctype="multipart/form-data">
      <div class="mb-3">
        <label class="form-label">Upload CSV/XLSX with <code>institute</code> column:</label>
        <input type="file" name="file" accept=".csv,.xls,.xlsx" class="form-control">
      </div>
      <div class="mb-3">
        <label class="form-label">Or paste institutes (one per line or comma-separated):</label>
        <textarea name="text_input" rows="4" class="form-control"></textarea>
      </div>
      <button type="submit" class="btn btn-primary">Start Geocoding</button>
    </form>
  {% else %}
    {% if pending %}
      <div class="alert alert-info">Job {{ job_id }} is processing... Please refresh this page.</div>
    {% elif results %}
      <h2 class="mt-4">Results for Job {{ job_id }}</h2>
      <div class="table-responsive">
        <table class="table table-bordered table-striped">
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
      <a href="/download/{{ job_id }}" class="btn btn-success mt-2">Download CSV</a>
    {% else %}
      <div class="alert alert-danger">Job {{ job_id }} not found.</div>
    {% endif %}
  {% endif %}
</body>
</html>'''

# Geocode a single institute name
def geocode_address(name):
    # Try ArcGIS
    try:
        loc = arcgis.geocode(name, exactly_one=True)
        if loc:
            return loc.latitude, loc.longitude
    except GeocoderServiceError:
        pass
    # Fallback to OSM
    for _ in range(2):
        try:
            loc = osm.geocode(name, exactly_one=True)
            if loc:
                return loc.latitude, loc.longitude
            # also try with "USA" bias
            loc = osm.geocode(f"{name}, USA", exactly_one=True)
            if loc:
                return loc.latitude, loc.longitude
        except (GeocoderTimedOut, GeocoderServiceError):
            time.sleep(1)
    return None, None

# Split input text into institute names, preserving parentheses
def split_names(text):
    names = []
    for line in text.splitlines():
        buf = ''
        depth = 0
        for ch in line:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth = max(depth-1, 0)
            if ch == ',' and depth == 0:
                if buf.strip():
                    names.append(buf.strip())
                buf = ''
            else:
                buf += ch
        if buf.strip():
            names.append(buf.strip())
    return names

# Batch geocode names concurrently, preserving order
def batch_geocode(names, workers=10):
    futures = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for name in names:
            futures.append((name, executor.submit(geocode_address, name)))
    results = []
    for name, fut in futures:
        try:
            lat, lon = fut.result()
        except Exception:
            lat, lon = (None, None)
        results.append((name, lat, lon))
    return results

# Main route: start or check job
@app.route('/', methods=['GET', 'POST'])
def index():
    job_id = request.args.get('job')
    if request.method == 'POST':
        # Parse names from file or text
        names = []
        f = request.files.get('file')
        if f and f.filename:
            try:
                df = pd.read_excel(f) if f.filename.lower().endswith(('.xls', '.xlsx')) else pd.read_csv(f)
                names = df['institute'].astype(str).tolist()
            except Exception:
                names = []
        if not names:
            text = request.form.get('text_input', '')
            names = split_names(text)
        if names:
            # Create job
            job_id = str(uuid.uuid4())
            jobs[job_id] = {'status': 'pending', 'results': None, 'csv': None}
            # Background thread
            def run(jid, name_list):
                res = batch_geocode(name_list)
                buf = io.StringIO()
                buf.write('institute,latitude,longitude\n')
                for inst, lat, lon in res:
                    buf.write(f"{inst},{lat or ''},{lon or ''}\n")
                jobs[jid]['results'] = res
                jobs[jid]['csv'] = buf.getvalue()
                jobs[jid]['status'] = 'done'
            Thread(target=run, args=(job_id, names), daemon=True).start()
            # Show status
            return render_template_string(TEMPLATE, job_id=job_id, pending=True)
    # If checking existing job
    if job_id:
        job = jobs.get(job_id)
        if job:
            if job['status'] == 'done':
                return render_template_string(TEMPLATE, job_id=job_id, results=job['results'])
            else:
                return render_template_string(TEMPLATE, job_id=job_id, pending=True)
    # Initial page
    return render_template_string(TEMPLATE)

# Download endpoint
@app.route('/download/<job_id>')
def download(job_id):
    job = jobs.get(job_id)
    if not job or job['status'] != 'done':
        return 'Not found or pending', 404
    data = job['csv']
    return send_file(
        io.BytesIO(data.encode('utf-8')),
        as_attachment=True,
        download_name=f'geocoded_{job_id}.csv',
        mimetype='text/csv'
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8000)))
