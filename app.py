# app.py
#!/usr/bin/env python3
from flask import Flask, render_template_string

app = Flask(__name__)

TEMPLATE = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\">
  <title>Institute Geocoder</title>
  <link rel=\"stylesheet\" href=\"https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css\"/>
  <script src=\"https://cdn.jsdelivr.net/npm/papaparse@5.3.2/papaparse.min.js\"></script>
  <script src=\"https://cdn.jsdelivr.net/npm/xlsx/dist/xlsx.full.min.js\"></script>
</head>
<body class=\"p-4\">
  <h1>Institute Geocoder</h1>

  <h2>Batch Upload (CSV/XLSX)</h2>
  <input type=\"file\" id=\"file-input\" accept=\".csv,.xls,.xlsx\" class=\"form-control mb-3\">
  <button id=\"process-file\" class=\"btn btn-primary mb-4\">Process File</button>

  <h2>Free Text Geocoding</h2>
  <textarea id=\"text-input\" rows=6 placeholder=\"One institute per line, or comma-separated\" class=\"form-control mb-3\"></textarea>
  <button id=\"process-text\" class=\"btn btn-secondary mb-4\">Process Text</button>

  <h2>Results</h2>
  <div class=\"table-responsive\"><table id=\"results-table\" class=\"table table-bordered table-striped\"><thead><tr><th>Institute</th><th>Latitude</th><th>Longitude</th></tr></thead><tbody></tbody></table></div>
  <button id=\"download-btn\" class=\"btn btn-success mt-2\" disabled>Download CSV</button>

  <script>
    // Census geocoding
    async function geocode(name) {
      let url = 'https://geocoding.geo.census.gov/geocoder/locations/onelineaddress';
      let params = new URLSearchParams({ address: name + ', USA', benchmark: 'Public_AR_Current', format: 'json' });
      try {
        let res = await fetch(`${url}?${params}`);
        let data = await res.json();
        let matches = data.result.addressMatches;
        if (matches && matches.length) {
          return [matches[0].coordinates.y, matches[0].coordinates.x];
        }
      } catch(e){}
      // fallback to Nominatim
      try {
        let nomUrl = 'https://nominatim.openstreetmap.org/search?format=json&q=' + encodeURIComponent(name + ', USA');
        let nomRes = await fetch(nomUrl);
        let nomData = await nomRes.json();
        if (nomData && nomData.length) {
          return [parseFloat(nomData[0].lat), parseFloat(nomData[0].lon)];
        }
      } catch(e){}
      return [null, null];
    }

    function enableDownload() {
      document.getElementById('download-btn').disabled = false;
    }

    document.getElementById('download-btn').addEventListener('click', () => {
      let rows = Array.from(document.querySelectorAll('#results-table tbody tr'));
      let csv = ['institute,latitude,longitude'];
      rows.forEach(r => {
        let cols = Array.from(r.children).map(td => td.textContent.trim());
        csv.push(cols.join(','));
      });
      let blob = new Blob([csv.join('\n')], { type: 'text/csv' });
      let url = URL.createObjectURL(blob);
      let a = document.createElement('a');
      a.href = url; a.download = 'geocoded.csv';
      a.click();
      URL.revokeObjectURL(url);
    });

    async function processList(list) {
      let tbody = document.querySelector('#results-table tbody');
      tbody.innerHTML = '';
      for (let name of list) {
        let tr = document.createElement('tr');
        tr.innerHTML = `<td>${name}</td><td>...</td><td>...</td>`;
        tbody.appendChild(tr);
        let [lat, lon] = await geocode(name);
        tr.children[1].textContent = lat !== null ? lat.toFixed(6) : '';
        tr.children[2].textContent = lon !== null ? lon.toFixed(6) : '';
      }
      enableDownload();
    }

    document.getElementById('process-file').addEventListener('click', () => {
      let input = document.getElementById('file-input').files[0];
      if (!input) return alert('Select a file first');
      let ext = input.name.split('.').pop().toLowerCase();
      if (ext === 'csv') {
        Papa.parse(input, { header: true, complete: (r) => {
          let names = r.data.map(o => o.institute).filter(Boolean);
          processList(names);
        }});
      } else {
        let reader = new FileReader();
        reader.onload = (e) => {
          let wb = XLSX.read(e.target.result, { type: 'binary' });
          let data = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]]);
          let names = data.map(o => o.institute).filter(Boolean);
          processList(names);
        };
        reader.readAsBinaryString(input);
      }
    });

    document.getElementById('process-text').addEventListener('click', () => {
      let text = document.getElementById('text-input').value;
      let lines = text.split(/[\r\n]+/).flatMap(l => l.split(/,(?![^()]*\))/));
      let names = lines.map(s => s.trim()).filter(Boolean);
      processList(names);
    });
  </script>
</body>
</html>"""

@app.route('/')
def index():
    return render_template_string(TEMPLATE)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8000)))
