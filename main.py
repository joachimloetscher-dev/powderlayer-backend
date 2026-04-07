from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import math
from typing import Dict, Optional
from datetime import datetime, timedelta, timezone

app = FastAPI(title="PowderLayer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
@app.head("/")
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
        # --- DIAGNOSTIC LOGS START ---
        print(f"--- DEBUG INFO ---")
        print(f"1. Target Date Received: {target_date}")
        
        zurich_tz = timezone(timedelta(hours=1))
        today = datetime.now(zurich_tz).date()
        print(f"2. Backend Server's 'Today' is: {today}")

        url = "https://api.open-meteo.com/v1/forecast"
        params = {"latitude": lat, "longitude": lon, "elevation": elevation, "timezone": "Europe/Zurich"}

        if target_date and target_hour is not None:
            try:
                clean_date = target_date.strip()
                req_date = datetime.strptime(clean_date, "%Y-%m-%d").date()
                print(f"3. Parsed Request Date: {req_date}")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format.")

            safe_hour = max(0, min(23, int(target_hour)))

            # RULE 1: Future Check
            if req_date > today + timedelta(days=14):
                print("4. ACTION: Request Blocked! Date is too far in the future.")
                raise HTTPException(status_code=400, detail="Forecast limit exceeded. Maximum 14 days in the future.")

            # RULE 2: History Check
            if req_date < today - timedelta(days=365):
                print("4. ACTION: Request Blocked! Date is too far in the past.")
                raise HTTPException(status_code=400, detail="Historical limit exceeded. Maximum 1 year in the past.")

            # RULE 3: Routing
            if req_date < today - timedelta(days=90):
                print("4. ACTION: Routing to Archive API")
                url = "https://archive-api.open-meteo.com/v1/archive"
            else:
                print("4. ACTION: Routing to standard Forecast API")
                url = "https://api.open-meteo.com/v1/forecast"

            params["hourly"] = "temperature_2m,wind_speed_10m"
            params["start_date"] = clean_date
            params["end_date"] = clean_date

        else:
            print("3. No target date provided. Fetching Live Weather.")
            params["current"] = "temperature_2m,wind_speed_10m"
            safe_hour = None

        print(f"5. Sending Request to Open-Meteo URL: {url}")
        # --- DIAGNOSTIC LOGS END ---

        try:
            response = requests.get(url, params=params, timeout=10.0)
            
            if response.status_code == 400:
                print(f"API REJECTED IT: {response.text}") # Print exact API complaint
                raise HTTPException(status_code=400, detail="Weather API rejected the parameters.")
                
            response.raise_for_status()
            data = response.json()
            
            if "hourly" in data:
                hour_str = f"{safe_hour:02d}:00"
                target_time = f"{clean_date}T{hour_str}"
                try:
                    time_index = data["hourly"]["time"].index(target_time)
                    temp = data["hourly"]["temperature_2m"][time_index]
                    wind = data["hourly"]["wind_speed_10m"][time_index]
                except ValueError:
                    temp = data["hourly"]["temperature_2m"][0]
                    wind = data["hourly"]["wind_speed_10m"][0]
            else:
                temp = data["current"]["temperature_2m"]
                wind = data["current"]["wind_speed_10m"]
                
            return {"temp": temp, "wind": wind, "feels_like": self._calculate_windchill(temp, wind)}
            
        except requests.exceptions.RequestException as e:
            print(f"CRITICAL WEATHER API ERROR: {str(e)}")
            raise HTTPException(status_code=503, detail="Weather Server unreachable. Please try again.")

    def get_layering_recommendation(self, resort_name: str, activity_level: str, user_offset: float, target_date: Optional[str], target_hour: Optional[int]) -> Dict:
        normalized_resort = resort_name.strip().lower()
        resort = next((r for r in self.resorts if r["name"] == normalized_resort), None)
        if not resort:
            raise HTTPException(status_code=404, detail="Ski Resort not found.")

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
