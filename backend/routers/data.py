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
from .colors import TEAM_COLORS, DRIVER_COLORS
from r2_client import get_json_cache, set_json_cache, safe_float
from fastf1.mvapi import get_circuit_info as mvapi_get_circuit_info


def extract_corners_from_circuit_info(circuit_info):
    """Extract corner distances from FastF1 circuit info without assuming timing cache data exists."""
    corners = []
    if circuit_info is None or not hasattr(circuit_info, 'corners'):
        return corners

    try:
        for _, corner in circuit_info.corners.iterrows():
            distance_value = corner['Distance']
            if pd.isna(distance_value):
                continue
            corners.append({
                "Number": int(corner['Number']),
                "Distance": safe_float(distance_value),
                "Letter": str(corner['Letter']) if not pd.isna(corner['Letter']) and corner['Letter'] else ""
            })
    except Exception as ce:
        print(f"Error extracting circuit corners: {ce}")

    return corners


def get_safe_circuit_info(sess):
    """Safely fetch circuit info, falling back to other drivers/laps if the fastest lap telemetry is missing."""
    try:
        # Try default FastF1 method first
        return sess.get_circuit_info()
    except Exception as e:
        print(f"Warning: Default get_circuit_info failed: {e}. Attempting fallback...")
        
    try:
        c_key = sess.session_info['Meeting']['Circuit']['Key']
        circuit_info = mvapi_get_circuit_info(year=sess.event.year, circuit_key=c_key)
        
        # Search for any lap in the session that has valid telemetry
        for _, lap in sess.laps.iterrows():
            try:
                tel = lap.get_telemetry()
                if tel is not None and not tel.empty and 'Distance' in tel.columns:
                    circuit_info.add_marker_distance(reference_lap=lap)
                    print(f"✓ Re-mapped corners using fallback reference lap from driver {lap['Driver']} (Lap {lap['LapNumber']})")
                    return circuit_info
            except Exception:
                continue
                
        print("Warning: No laps with valid telemetry found. Returning corners without distance markers.")
        return circuit_info
    except Exception as ex:
        print(f"Error in get_safe_circuit_info fallback: {ex}")
        return None

router = APIRouter()

@router.get("/standings")
def get_standings(year: int):
    try:
        url = f"https://api.jolpi.ca/ergast/f1/{year}/driverStandings.json"
        
        response = urlopen(url)
        data = json.loads(response.read().decode('utf-8'))
        
        standings_list = data.get('MRData', {}).get('StandingsTable', {}).get('StandingsLists', [])
        if not standings_list:
            return []
            
        driver_standings = standings_list[0].get('DriverStandings', [])
        
        standings = []
        for row in driver_standings:
            driver = row.get('Driver', {})
            constructors = row.get('Constructors', [])
            constructor = constructors[0] if constructors else {'name': 'Unknown', 'constructorId': ''}
            
            standings.append({
                'DriverNumber': int(driver.get('permanentNumber', 0)),
                'Driver': f"{driver.get('givenName', '')} {driver.get('familyName', '')}",
                'Points': float(row.get('points', 0)),
                'Team': constructor.get('name', 'Unknown'),
                'Color': TEAM_COLORS.get(constructor.get('constructorId', ''), '#FFFFFF')
            })
            
        return standings

    except Exception as e:
        print(f"Standings error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/race-pace")
def get_race_pace(year: int, gp: str, session: str, drivers: str):
    # drivers: comma separated short names e.g. "VER,HAM"
    driver_list = [d.strip() for d in drivers.split(',')]
    
    try:
        cache_key = f"timing/{year}/{gp}/{session}/laps.json"
        cached_data = get_json_cache(cache_key)
        
        if cached_data:
            print(f"Race Pace Cache Hit for {year} {gp} {session}")
            response_drivers = []
            for drv in driver_list:
                if drv in cached_data["Drivers"]:
                    drv_data = cached_data["Drivers"][drv]
                    response_drivers.append({
                        "Driver": drv,
                        "Color": DRIVER_COLORS.get(drv, '#FFFFFF'),
                        "Laps": drv_data["Laps"]
                    })
            return {"TotalLaps": cached_data["TotalLaps"], "Drivers": response_drivers}
            
        print(f"Race Pace Cache Miss for {year} {gp} {session}. Fetching from FastF1...")
        sess = fastf1.get_session(year, gp, session)
        sess.load(messages=False, weather=False, telemetry=False)
        
        response_data = []

        # Get the total number of laps in the session
        total_laps = int(sess.laps['LapNumber'].max()) if not sess.laps.empty else 0

        # Get all unique drivers who set a lap
        all_drivers = list(sess.laps['Driver'].unique()) if not sess.laps.empty else []
        
        full_cache_data = {
            "TotalLaps": total_laps,
            "Drivers": {}
        }

        for drv in all_drivers:
            try:
                laps = sess.laps.pick_drivers(drv).pick_wo_box().pick_quicklaps()
                if laps.empty:
                    continue
                
                lap_data = []
                for idx, row in laps.iterrows():
                    lap_data.append({
                        "LapNumber": int(row['LapNumber']),
                        "LapTime": row['LapTime'].total_seconds()
                    })
                
                full_cache_data["Drivers"][drv] = {
                    "Driver": drv,
                    "Laps": lap_data
                }
            except Exception as e:
                print(f"Error caching race pace for driver {drv}: {e}")
                continue
                
        # Write to R2 cache
        set_json_cache(cache_key, full_cache_data)
        
        # Prepare response for requested drivers
        response_drivers = []
        for drv in driver_list:
            if drv in full_cache_data["Drivers"]:
                drv_data = full_cache_data["Drivers"][drv]
                response_drivers.append({
                    "Driver": drv,
                    "Color": DRIVER_COLORS.get(drv, '#FFFFFF'),
                    "Laps": drv_data["Laps"]
                })
                
        return {"TotalLaps": total_laps, "Drivers": response_drivers}

    except Exception as e:
        print(f"Race pace error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/telemetry")
def get_telemetry(year: int, gp: str, session: str, driver1: str, driver2: str, lap1: str = 'fastest', lap2: str = 'fastest'):
    try:
        key1 = f"telemetry/{year}/{gp}/{session}/{driver1}_{lap1}.json"
        key2 = f"telemetry/{year}/{gp}/{session}/{driver2}_{lap2}.json"
        
        data1 = get_json_cache(key1)
        data2 = get_json_cache(key2)
        
        # Check if both are cached
        if data1 and data2:
            print(f"Telemetry Cache Hit for {driver1} ({lap1}) and {driver2} ({lap2})")
            
            # Fetch corners from circuit corners cache if available; otherwise compute and cache them.
            corners_key = f"circuit/{year}/{gp}/corners.json"
            corners = get_json_cache(corners_key)
            if not corners:
                try:
                    sess = fastf1.get_session(year, gp, session)
                    sess.load(weather=False, messages=False)
                    circuit_info = get_safe_circuit_info(sess)
                    corners = extract_corners_from_circuit_info(circuit_info)
                    if corners:
                        set_json_cache(corners_key, corners)
                except Exception as ce:
                    print(f"Error fetching corners for cached hit: {ce}")
                    corners = []

            # Reconstruct Delta using NumPy interpolation
            d1_telemetry = data1["Telemetry"]
            d2_telemetry = data2["Telemetry"]
            
            d1_dist = [p["Distance"] for p in d1_telemetry]
            d1_time = [p["Time"] for p in d1_telemetry]
            
            d2_dist = [p["Distance"] for p in d2_telemetry]
            d2_time = [p["Time"] for p in d2_telemetry]
            
            delta_data = []
            if d1_dist and d2_dist:
                comp_time_interpolated = np.interp(d1_dist, d2_dist, d2_time)
                delta = comp_time_interpolated - np.array(d1_time)
                for i in range(len(d1_dist)):
                    delta_data.append({
                        "Distance": safe_float(d1_dist[i]),
                        "Delta": safe_float(delta[i])
                    })
                    
            return {
                "Driver1": {
                    "Name": driver1,
                    "Color": DRIVER_COLORS.get(driver1, '#FFFFFF'),
                    "Telemetry": d1_telemetry,
                    "LapTime": data1["LapTime"]
                },
                "Driver2": {
                    "Name": driver2,
                    "Color": DRIVER_COLORS.get(driver2, '#FFFFFF'),
                    "Telemetry": d2_telemetry,
                    "LapTime": data2["LapTime"]
                },
                "Delta": delta_data,
                "Corners": corners
            }

        # Cache Miss - load session from FastF1
        print(f"Telemetry Cache Miss. Fetching from FastF1...")
        sess = fastf1.get_session(year, gp, session)
        sess.load(weather=False, messages=False)
        
        # Helper to get lap
        def get_driver_lap(drv, lap_identifier):
            d_laps = sess.laps.pick_drivers(drv)
            if lap_identifier == 'fastest':
                return d_laps.pick_fastest()
            else:
                return d_laps.pick_laps(int(lap_identifier)).iloc[0]
                
        lap_d1 = get_driver_lap(driver1, lap1)
        lap_d2 = get_driver_lap(driver2, lap2)
        
        tel_d1 = lap_d1.get_telemetry().add_distance()
        tel_d2 = lap_d2.get_telemetry().add_distance()
        
        # Calculate Delta
        delta_time, ref_tel, compare_tel = utils.delta_time(lap_d1, lap_d2)
        
        # Get Circuit Info (Corners)
        corners_key = f"circuit/{year}/{gp}/corners.json"
        corners = get_json_cache(corners_key)
        if not corners:
            try:
                circuit_info = get_safe_circuit_info(sess)
                corners = extract_corners_from_circuit_info(circuit_info)
                if corners:
                    set_json_cache(corners_key, corners)
            except Exception as ce:
                print(f"Error fetching/caching corners: {ce}")
                corners = []
                  
        def process_tel(tel):
            data = []
            for i in range(len(tel)):
                data.append({
                    "Distance": safe_float(tel['Distance'].iloc[i]),
                    "Speed": safe_float(tel['Speed'].iloc[i]),
                    "Throttle": safe_float(tel['Throttle'].iloc[i]),
                    "Brake": safe_float(tel['Brake'].iloc[i]),
                    "RPM": safe_float(tel['RPM'].iloc[i]),
                    "nGear": int(tel['nGear'].iloc[i]) if not pd.isna(tel['nGear'].iloc[i]) else 0,
                    "DRS": int(tel['DRS'].iloc[i]) if not pd.isna(tel['DRS'].iloc[i]) else 0,
                    "Time": safe_float(tel['Time'].iloc[i].total_seconds())
                })
            return data
            
        d1_data = process_tel(tel_d1)
        d2_data = process_tel(tel_d2)
        
        delta_data = []
        for i in range(len(delta_time)):
             delta_data.append({
                 "Distance": safe_float(ref_tel['Distance'].iloc[i]),
                 "Delta": safe_float(delta_time[i])
             })
             
        # Save cache files to R2
        if not data1:
            d1_cache = {
                "Driver": driver1,
                "LapNumber": lap1,
                "LapTime": float(lap_d1['LapTime'].total_seconds()),
                "Telemetry": d1_data
            }
            set_json_cache(key1, d1_cache)
            
        if not data2:
            d2_cache = {
                "Driver": driver2,
                "LapNumber": lap2,
                "LapTime": float(lap_d2['LapTime'].total_seconds()),
                "Telemetry": d2_data
            }
            set_json_cache(key2, d2_cache)
            
        # No longer updating corners in session timing file since they are stored in a dedicated circuit-level cache
            
        c1 = DRIVER_COLORS.get(driver1, '#FFFFFF')
        c2 = DRIVER_COLORS.get(driver2, '#FFFFFF')
        
        return {
            "Driver1": {
                "Name": driver1,
                "Color": c1,
                "Telemetry": d1_data,
                "LapTime": lap_d1['LapTime'].total_seconds()
            },
            "Driver2": {
                "Name": driver2,
                "Color": c2,
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

@router.get("/drivers")
def get_drivers(year: int, gp: str, sess_type: str):
    try:
        session = fastf1.get_session(year, gp, sess_type)
        session.load(telemetry=False, weather=False, messages=False, laps=False)
        drivers = session.results[['Abbreviation', 'FullName']]
        return [{"Name": d[2], "Driver": d[1]} for d in drivers.itertuples()]
    except Exception as e:
        return {"error": str(e)}