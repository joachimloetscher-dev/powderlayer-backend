from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import math
from typing import Dict

app = FastAPI(title="PowderLayer API")

# Allow Lovable to talk to this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

class PowderLayerEngine:
    def __init__(self):
        self.resorts = [
            { "name": "zermatt", "lat": 46.02, "lon": 7.75, "alt_base": 1620, "alt_peak": 3883 },
            { "name": "st. moritz", "lat": 46.50, "lon": 9.84, "alt_base": 1735, "alt_peak": 3057 },
            { "name": "davos klosters", "lat": 46.80, "lon": 9.83, "alt_base": 1560, "alt_peak": 2844 },
            { "name": "verbier", "lat": 46.10, "lon": 7.23, "alt_base": 1500, "alt_peak": 3330 },
            { "name": "laax", "lat": 46.83, "lon": 9.22, "alt_base": 1100, "alt_peak": 3018 },
            { "name": "arosa lenzerheide", "lat": 46.78, "lon": 9.68, "alt_base": 1230, "alt_peak": 2865 },
            { "name": "adelboden", "lat": 46.49, "lon": 7.56, "alt_base": 1350, "alt_peak": 2400 },
            { "name": "engelberg", "lat": 46.82, "lon": 8.41, "alt_base": 1050, "alt_peak": 3020 },
            { "name": "grindelwald", "lat": 46.62, "lon": 8.04, "alt_base": 1034, "alt_peak": 2970 },
            { "name": "saas-fee", "lat": 46.11, "lon": 7.93, "alt_base": 1800, "alt_peak": 3573 }
        ]
        self.activity_multipliers = {"low": 1.2, "medium": 1.0, "high": 0.7}

    def _calculate_windchill(self, temp_c: float, wind_kmh: float) -> float:
        if temp_c <= 10.0 and wind_kmh > 4.8:
            windchill = 13.12 + (0.6215 * temp_c) - (11.37 * math.pow(wind_kmh, 0.16)) + (0.3965 * temp_c * math.pow(wind_kmh, 0.16))
            return round(windchill, 1)
        return temp_c

    def _fetch_weather(self, lat: float, lon: float, elevation: int) -> Dict:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {"latitude": lat, "longitude": lon, "elevation": elevation, "current": "temperature_2m,wind_speed_10m", "timezone": "Europe/Zurich"}
        try:
            response = requests.get(url, params=params, timeout=5.0)
            response.raise_for_status()
            data = response.json()
            temp = data["current"]["temperature_2m"]
            wind = data["current"]["wind_speed_10m"]
            return {"temp": temp, "wind": wind, "feels_like": self._calculate_windchill(temp, wind)}
        except Exception as e:
            raise HTTPException(status_code=502, detail="Weather API unavailable")

    def get_layering_recommendation(self, resort_name: str, activity_level: str, user_offset: float) -> Dict:
        normalized_resort = resort_name.strip().lower()
        resort = next((r for r in self.resorts if r["name"] == normalized_resort), None)
        if not resort:
            raise HTTPException(status_code=404, detail="Resort not found")

        weather_base = self._fetch_weather(resort["lat"], resort["lon"], resort["alt_base"])
        weather_peak = self._fetch_weather(resort["lat"], resort["lon"], resort["alt_peak"])

        base_required_clo = max(0.0, (31.0 - weather_peak["feels_like"]) * 0.05)
        multiplier = self.activity_multipliers.get(activity_level.strip().lower(), 1.0)
        final_required_clo = max(0.0, (base_required_clo * multiplier) + float(user_offset))

        return {
            "resort": resort["name"].title(), 
            "weather": {"base": {"elevation": resort["alt_base"], **weather_base}, "peak": {"elevation": resort["alt_peak"], **weather_peak}},
            "required_clo": round(final_required_clo, 2)
        }

engine = PowderLayerEngine()

@app.get("/recommendation")
def get_recommendation(resort_name: str, activity_level: str = "medium", user_offset: float = 0.0):
    return engine.get_layering_recommendation(resort_name, activity_level, user_offset)

@app.get("/feedback")
def calculate_new_offset(current_offset: float, feedback: str):
    step = 0.05
    normalized_feedback = feedback.strip().title()
    if normalized_feedback == "Freezing":
        new_offset = float(current_offset) + step
    elif normalized_feedback == "Sweating":
        new_offset = float(current_offset) - step
    else:
        return {"new_offset": current_offset}
    return {"new_offset": max(-0.5, min(0.5, round(new_offset, 2)))}
