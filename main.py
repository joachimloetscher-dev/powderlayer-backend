from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import math
from typing import Dict, Optional

app = FastAPI(title="PowderLayer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"status": "PowderLayer API is running and healthy"}

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

    def _fetch_weather(self, lat: float, lon: float, elevation: int, target_date: Optional[str], target_hour: Optional[int]) -> Dict:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "elevation": elevation,
            "timezone": "Europe/Zurich"
        }

        # If frontend sent a specific date and hour, use the hourly forecast
        if target_date and target_hour is not None:
            params["hourly"] = "temperature_2m,wind_speed_10m"
            params["start_date"] = target_date
            params["end_date"] = target_date
        else:
            # Otherwise, just get the weather right now
            params["current"] = "temperature_2m,wind_speed_10m"

        try:
            response = requests.get(url, params=params, timeout=10.0)
            
            # Catch Open-Meteo's specific 400 error (Usually caused by asking for dates > 14 days in future)
            if response.status_code == 400:
                raise HTTPException(status_code=400, detail="Date out of range. Weather forecast is only available for the next 14 days.")
                
            response.raise_for_status()
            data = response.json()
            
            if "hourly" in data:
                # Format target time to match Open-Meteo (e.g., "2026-04-07T07:00")
                hour_str = f"{int(target_hour):02d}:00"
                target_time = f"{target_date}T{hour_str}"
                
                try:
                    time_index = data["hourly"]["time"].index(target_time)
                    temp = data["hourly"]["temperature_2m"][time_index]
                    wind = data["hourly"]["wind_speed_10m"][time_index]
                except ValueError:
                    # If exact hour isn't found, fallback safely to the first hour of that day
                    temp = data["hourly"]["temperature_2m"][0]
                    wind = data["hourly"]["wind_speed_10m"][0]
            else:
                temp = data["current"]["temperature_2m"]
                wind = data["current"]["wind_speed_10m"]
                
            return {"temp": temp, "wind": wind, "feels_like": self._calculate_windchill(temp, wind)}
            
        except requests.exceptions.RequestException as e:
            print(f"WEATHER API ERROR: {str(e)}")
            raise HTTPException(status_code=502, detail=f"Weather API unavailable: {str(e)}")

    def get_layering_recommendation(self, resort_name: str, activity_level: str, user_offset: float, target_date: Optional[str], target_hour: Optional[int]) -> Dict:
        normalized_resort = resort_name.strip().lower()
        resort = next((r for r in self.resorts if r["name"] == normalized_resort), None)
        if not resort:
            raise HTTPException(status_code=404, detail="Resort not found")

        weather_base = self._fetch_weather(resort["lat"], resort["lon"], resort["alt_base"], target_date, target_hour)
        weather_peak = self._fetch_weather(resort["lat"], resort["lon"], resort["alt_peak"], target_date, target_hour)

        base_required_clo = max(0.0, (31.0 - weather_peak["feels_like"]) * 0.05)
        multiplier = self.activity_multipliers.get(activity_level.strip().lower(), 1.0)
        final_required_clo = max(0.0, (base_required_clo * multiplier) + float(user_offset))

        return {
            "resort": resort["name"].title(), 
            "weather": {"base": {"elevation": resort["alt_base"], **weather_base}, "peak": {"elevation": resort["alt_peak"], **weather_peak}},
            "required_clo": round(final_required_clo, 2)
        }

engine = PowderLayerEngine()

# The endpoint now explicitly accepts 'date' and 'hour'
@app.get("/recommendation")
def get_recommendation(resort_name: str, activity_level: str = "medium", user_offset: float = 0.0, date: Optional[str] = None, hour: Optional[int] = None):
    return engine.get_layering_recommendation(resort_name, activity_level, user_offset, date, hour)

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
