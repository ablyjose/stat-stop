from fastapi import APIRouter, HTTPException
from urllib.request import urlopen
from urllib.error import HTTPError
import json
import pandas as pd
import numpy as np
import fastf1
from fastf1 import utils
import time
from datetime import date
from pathlib import Path
import os

router = APIRouter()

# --- Helper for OpenF1 caching ---
# We use a separate cache for OpenF1 responses to avoid spamming the API
CACHE_DIR = Path("web-app/cache/openF1") 
# Handle relative path if running from different location, though main.py sets cwd usually?
# Let's use absolute path relative to this file to be safe
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent # PortProjects/Formula1
CACHE_DIR = BASE_DIR / "web-app/cache/openF1"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def fetch_openf1(url, cache_key=None, use_cache=True):
    if use_cache and cache_key:
        file_path = CACHE_DIR / f"{cache_key}.json"
        if file_path.exists():
            with open(file_path, "r") as f:
                return json.load(f)

    # Fetch
    try:
        response = urlopen(url)
        data = json.loads(response.read().decode('utf-8'))
    except HTTPError as e:
        # Retry once
        time.sleep(0.5)
        response = urlopen(url)
        data = json.loads(response.read().decode('utf-8'))
    
    if use_cache and cache_key and data:
        with open(file_path, "w") as f:
            json.dump(data, f)
            
    return data

@router.get("/standings")
def get_standings(year: int = 2026):
    try:
        # 1. Get Schedule
        schedule_data = fetch_openf1(
            f"https://api.openf1.org/v1/sessions?date_start>={year}-01-01&date_end<={min(str(date.today()), f'{year}-12-31')}&session_type=Race",
            use_cache=False
        )
        schedule = pd.DataFrame(schedule_data)
        
        if schedule.empty:
            return []

        schedule = schedule[schedule['is_cancelled'] == False]
        session_keys = schedule['session_key'].tolist()
        
        # 2. Get Initial Drivers (from first session) to easier initialize df
        # Note: Logic adapted from global driver list approach might be better, 
        # but following original script's flow:
        first_session_drivers = fetch_openf1(
            f"https://api.openf1.org/v1/drivers?session_key={session_keys[0]}",
            cache_key=f"drivers_{session_keys[0]}"
        )
        drivers_df = pd.DataFrame(first_session_drivers)
        
        standings = pd.DataFrame({
            'DriverNumber': drivers_df['driver_number'],
            'Driver': drivers_df['full_name'],
            'Points': 0.0,
            'Team': drivers_df['team_name'],
            'Color': drivers_df['team_colour'] # Added color for UI
        })
        
        # 3. Iterate sessions
        for key in session_keys:
            session_result = fetch_openf1(
                f"https://api.openf1.org/v1/session_result?session_key={key}",
                cache_key=f"result_{key}"
            )
            results = pd.DataFrame(session_result)
            
            if results.empty:
                continue

            for index, row in results.iterrows():
                driver_number = row['driver_number']
                points = row['points']
                
                if driver_number in standings['DriverNumber'].values:
                    standings.loc[standings['DriverNumber'] == driver_number, 'Points'] += points
                else:
                    # Fetch new driver info if not in list
                    # Verify cache key uniqueness for driver+session
                    new_driver_data = fetch_openf1(
                        f"https://api.openf1.org/v1/drivers?driver_number={driver_number}&session_key={key}",
                        cache_key=f"driver_{driver_number}_{key}"
                    )
                    new_driver = pd.DataFrame(new_driver_data)
                    if not new_driver.empty:
                        new_row = pd.DataFrame({
                            'DriverNumber': new_driver['driver_number'],
                            'Driver': new_driver['full_name'],
                            'Points': points,
                            'Team': new_driver['team_name'],
                            'Color': new_driver['team_colour']
                        })
                        standings = pd.concat([standings, new_row], ignore_index=True)

        updated_standings = standings.sort_values(by='Points', ascending=False).reset_index(drop=True)
        updated_standings = updated_standings.fillna('') # Handle NaN for JSON
        
        return updated_standings.to_dict(orient='records')

    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/race-pace")
def get_race_pace(year: int, gp: str, session: str, drivers: str):
    # drivers: comma separated short names e.g. "VER,HAM"
    driver_list = [d.strip() for d in drivers.split(',')]
    
    try:
        # Load session
        # Use session identifier (e.g. 'R' for Race)
        # Note: fastf1 might need cache dir set globally in main.py, which we did.
        
        # Map generic names to specific enough queries?
        # User input might need to be flexible.
        # fastf1.get_session(year, gp, session) accepts (2025, 'Brazil', 'R')
        
        sess = fastf1.get_session(year, gp, session)
        sess.load(messages=False, weather=False)
        
        response_data = []

        # Get the total number of laps in the session
        total_laps = int(sess.laps['LapNumber'].max()) if not sess.laps.empty else 0

        for drv in driver_list:
            try:
                laps = sess.laps.pick_drivers(drv).pick_wo_box().pick_quicklaps()
                if laps.empty:
                    continue
                
                # Get Color
                drv_info = sess.get_driver(drv)
                color = '#' + drv_info['TeamColor'] if drv_info['TeamColor'] else '#000000'
                
                # Prepare data points
                # Returning list of {lap: int, time: float (seconds)}
                lap_data = []
                for idx, row in laps.iterrows():
                    lap_data.append({
                        "LapNumber": int(row['LapNumber']),
                        "LapTime": row['LapTime'].total_seconds()
                    })
                
                response_data.append({
                    "Driver": drv,
                    "Color": color,
                    "Laps": lap_data
                })
            except Exception as e:
                print(f"Error for driver {drv}: {e}")
                continue
                
        return {"TotalLaps": total_laps, "Drivers": response_data}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/telemetry")
def get_telemetry(year: int, gp: str, session: str, driver1: str, driver2: str, lap1: str = 'fastest', lap2: str = 'fastest'):
    try:
        sess = fastf1.get_session(year, gp, session)
        sess.load(weather=False, messages=False) # Load light
        
        # Helper to get lap
        def get_driver_lap(drv, lap_identifier):
            d_laps = sess.laps.pick_drivers(drv)
            if lap_identifier == 'fastest':
                return d_laps.pick_fastest()
            else:
                return d_laps.pick_laps(int(lap_identifier)).iloc[0] # pick_laps return slice?
        
        # Handle qualifying split? telTest has special logic for Q.
        # But get_session works generally.
        # If Q, we might need split_qualifying_sessions logic if we want specific Q session part.
        # For simplicity, let's assume 'Q' loads the full quali session and we just pick fastest from it.
        
        lap_d1 = get_driver_lap(driver1, lap1)
        lap_d2 = get_driver_lap(driver2, lap2)
        
        tel_d1 = lap_d1.get_telemetry().add_distance()
        tel_d2 = lap_d2.get_telemetry().add_distance()
        
        # Calculate Delta
        delta_time, ref_tel, compare_tel = utils.delta_time(lap_d1, lap_d2)
        
        # Get Circuit Info (Corners)
        circuit_info = sess.get_circuit_info()
        corners = []
        if circuit_info is not None:
             for _, corner in circuit_info.corners.iterrows():
                 corners.append({
                     "Number": int(corner['Number']),
                     "Distance": float(corner['Distance']),
                     "Letter": corner['Letter'] if not pd.isna(corner['Letter']) else ""
                 })
        
        # We need to structure this for the frontend.
        # Option: Return one large array of objects merged by distance?
        # Or separate arrays.
        # Frontend likely wants to map X-axis (Distance) to Y-values.
        # Since distances aren't identical steps, we might need to interpolation?
        # Actually, Charts usually handle multiple series if X is same type.
        # But for 'Delta', the X axis is ref_tel['Distance'].
        
        # Simplified: Return 3 series: Driver1 Tel, Driver2 Tel, Delta
        
        def process_tel(tel, drv_name):
            data = []
            for i in range(len(tel)):
                data.append({
                    "Distance": float(tel['Distance'].iloc[i]),
                    "Speed": float(tel['Speed'].iloc[i]),
                    "Throttle": float(tel['Throttle'].iloc[i]),
                    "Brake": float(tel['Brake'].iloc[i]),
                    "RPM": float(tel['RPM'].iloc[i]),
                    "nGear": int(tel['nGear'].iloc[i]),
                    "DRS": int(tel['DRS'].iloc[i]),
                    "Time": float(tel['Time'].iloc[i].total_seconds())
                })
            return data
            
        d1_data = process_tel(tel_d1, driver1)
        d2_data = process_tel(tel_d2, driver2)
        
        delta_data = []
        for i in range(len(delta_time)):
             delta_data.append({
                 "Distance": float(ref_tel['Distance'].iloc[i]),
                 "Delta": float(delta_time[i])
             })
             
        # Colors

        driver_colors = {
            'NOR': '#D2FF00',
            'PIA': '#FF8F00',
            'RUS': '#00D2BE',
            'ANT': '#ADD8E6',
            'VER': '#3671C6',
            'TSU': '#1A2C80',
            'LEC': '#DC0000',
            'HAM': '#800080',
            'ALB': '#FFCCC7',
            'SAI': '#0082FA',
            'HAD': '#12264F',
            'LAW': '#F9F871',
            'ALO': '#006F62',
            'STR': '#006F62',
            'OCO': '#F7F7F7',
            'BEA': '#FF007F',
            'HUL': '#39FF14',
            'BOR': '#009739',
            'GAS': '#4E90FF',
            'COL': '#04299C',
        }

        if (driver1 in driver_colors):
            c1 = driver_colors.get(driver1)
        else:
            c1 = '#'+ sess.get_driver(driver1)['TeamColor']
        
        if (driver2 in driver_colors):
            c2 = driver_colors.get(driver2)
        else:
            c2 = '#'+sess.get_driver(driver2)['TeamColor']
        
        return {
            "Driver1": {
                "Name": driver1,
                "Color": c1 if c1 else "#000000",
                "Telemetry": d1_data,
                "LapTime": lap_d1['LapTime'].total_seconds()
            },
            "Driver2": {
                "Name": driver2,
                "Color": c2 if c2 else "#000000",
                "Telemetry": d2_data,
                "LapTime": lap_d2['LapTime'].total_seconds()
            },
            "Delta": delta_data,
            "Corners": corners
        }
        
    except Exception as e:
        print(f"Telemetry error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/events")
def get_events(year: int = 2026):
    try:
        schedule = fastf1.get_event_schedule(year)
        events = []
        for i, row in schedule.iterrows():
            # Skip testing?
            if "Test" in row['EventName']:
                continue
                
            events.append({
                "RoundNumber": int(row['RoundNumber']) if row['RoundNumber'] else 0,
                "EventName": row['EventName'],
                "Country": row['Country'],
                "Location": row['Location'],
                "EventDate": row['EventDate'].isoformat(),
                "OfficialEventName": row['OfficialEventName']
            })
        return events
    except Exception as e:
        return {"error": str(e)}
