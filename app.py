from flask import Flask, request, render_template_string
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

app = Flask(__name__)
geolocator = Nominatim(user_agent="InstituteLocatorApp/1.0")

HTML = """
<!doctype html>
<title>Institute Geolocation Finder</title>
<h1>🏫 Institute Geolocation Finder</h1>
<form method="post">
  <input name="query" placeholder="e.g. Temple University" style="width:300px"/>
  <button type="submit">Find</button>
</form>
{% if result %}
  <p>Latitude: {{ result.lat }}<br/>Longitude: {{ result.lon }}</p>
{% elif error %}
  <p style="color:red">{{ error }}</p>
{% endif %}
"""

@app.route("/", methods=["GET","POST"])
def index():
    result = error = None
    if request.method=="POST":
        q = request.form.get("query","").strip()
        if not q:
            error = "Please enter a query."
        else:
            try:
                loc = geolocator.geocode(q, timeout=10)
                if loc:
                    result = {"lat": f"{loc.latitude:.6f}", "lon": f"{loc.longitude:.6f}"}
                else:
                    error = "No match found."
            except GeocoderTimedOut:
                error = "Geocoding timed out, try again."
    return render_template_string(HTML, result=result, error=error)

if __name__=="__main__":
    app.run(host="0.0.0.0", port=8000)
