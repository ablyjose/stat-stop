from fastapi import APIRouter, HTTPException
from urllib.request import urlopen
import json
import pandas as pd
import numpy as np
import fastf1
from .colors import TEAM_COLORS, DRIVER_COLORS
try:
    from ..telemetry import calculate_telemetry_delta, get_lap_telemetry
    from ..r2_client import (get_json_cache, set_json_cache, safe_float, telemetry_cache_key,
                             valid_race_pace, read_circuit_corners, circuit_corners_payload)
except ImportError:  # Supports running the backend directly from its directory.
    from telemetry import calculate_telemetry_delta, get_lap_telemetry
    from r2_client import (get_json_cache, set_json_cache, safe_float, telemetry_cache_key,
                           valid_race_pace, read_circuit_corners, circuit_corners_payload)
from fastf1.mvapi import get_circuit_info as mvapi_get_circuit_info


def extract_corners_from_circuit_info(circuit_info):
    """Extract corner distances from FastF1 circuit info without assuming timing cache data exists."""
    corners = []
    if circuit_info is None or not hasattr(circuit_info, 'corners'):
        return corners

    try:
        for _, corner in circuit_info.corners.iterrows():
            distance_value = corner['Distance']
            if not np.isfinite(distance_value):
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
        if circuit_info is None:
            return None
        
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
        raise RuntimeError("Circuit source is unavailable") from ex

router = APIRouter()

SESSION_KEY_MAP = {
    'Practice 1': 'FP1',
    'Practice 2': 'FP2',
    'Practice 3': 'FP3',
    'Sprint Shootout': 'SS',
    'Sprint Qualifying': 'SQ',
    'Sprint': 'S',
    'Qualifying': 'Q',
    'Race': 'R',
}

@router.get("/standings")
def get_standings(year: int):
    try:
        url = f"https://api.jolpi.ca/ergast/f1/{year}/driverStandings.json"
        
        with urlopen(url, timeout=30) as response:
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
        
        if valid_race_pace(cached_data):
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
        
        # Get the total number of laps in the session
        total_laps = int(sess.laps['LapNumber'].max()) if not sess.laps.empty else 0

        # Get all unique drivers who set a lap
        all_drivers = list(sess.laps['Driver'].unique()) if not sess.laps.empty else []
        
        full_cache_data = {
            "TotalLaps": total_laps,
            "Drivers": {}
        }
        failed_drivers = []

        for drv in all_drivers:
            try:
                laps = sess.laps.pick_drivers(drv).pick_wo_box().pick_quicklaps()
                if laps.empty:
                    continue
                
                lap_data = []
                for idx, row in laps.iterrows():
                    if pd.isna(row['LapTime']) or pd.isna(row['LapNumber']):
                        continue
                    lap_data.append({
                        "LapNumber": int(row['LapNumber']),
                        "LapTime": row['LapTime'].total_seconds()
                    })
                
                if not lap_data:
                    continue
                full_cache_data["Drivers"][drv] = {
                    "Driver": drv,
                    "Laps": lap_data
                }
            except Exception as e:
                print(f"Error caching race pace for driver {drv}: {e}")
                failed_drivers.append(drv)
                continue
                
        if failed_drivers or not valid_race_pace(full_cache_data):
            raise HTTPException(status_code=503, detail="Lap timing is unavailable from FastF1. Check source access and authentication.")
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

    except HTTPException:
        raise
    except Exception as e:
        print(f"Race pace error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/telemetry")
def get_telemetry(year: int, gp: str, session: str, driver1: str, driver2: str, lap1: str = 'fastest', lap2: str = 'fastest'):
    key1 = telemetry_cache_key(year, gp, session, driver1, lap1)
    key2 = telemetry_cache_key(year, gp, session, driver2, lap2)
    try:
        data1 = get_json_cache(key1)
        data2 = get_json_cache(key2)

        if not (data1 and data2):
            print("Telemetry Cache Miss. Fetching from FastF1...")
            sess = fastf1.get_session(year, gp, session)
            sess.load(weather=False, messages=False)

            def get_driver_lap(driver, lap_identifier):
                driver_laps = sess.laps.pick_drivers(driver)
                if lap_identifier == "fastest":
                    lap = driver_laps.pick_fastest()
                    if lap is None:
                        raise HTTPException(status_code=404, detail=f"No timed lap available for {driver}.")
                    return lap
                lap_number = int(lap_identifier)
                if lap_number <= 0:
                    raise ValueError("Lap number must be positive")
                laps = driver_laps.pick_laps(lap_number)
                if laps.empty:
                    raise HTTPException(status_code=404, detail=f"Lap {lap_number} is unavailable for {driver}.")
                return laps.iloc[0]

            def process_tel(tel):
                return [{
                    "Distance": float(tel["Distance"].iloc[i]),
                    "Speed": safe_float(tel["Speed"].iloc[i]),
                    "Throttle": safe_float(tel["Throttle"].iloc[i]),
                    "Brake": safe_float(tel["Brake"].iloc[i]),
                    "RPM": safe_float(tel["RPM"].iloc[i]),
                    "nGear": int(tel["nGear"].iloc[i]) if not pd.isna(tel["nGear"].iloc[i]) else 0,
                    "DRS": int(tel["DRS"].iloc[i]) if not pd.isna(tel["DRS"].iloc[i]) else 0,
                    "Time": float(tel["Time"].iloc[i].total_seconds()),
                } for i in range(len(tel))]

            def load_driver(driver, lap_identifier, key):
                lap = get_driver_lap(driver, lap_identifier)
                telemetry = process_tel(get_lap_telemetry(lap))
                calculate_telemetry_delta(telemetry, telemetry)
                lap_time = lap["LapTime"]
                result = {
                    "Driver": driver, "LapNumber": lap_identifier,
                    "LapTime": safe_float(lap_time.total_seconds(), None) if pd.notna(lap_time) else None,
                    "Telemetry": telemetry,
                }
                set_json_cache(key, result)
                return result

            data1 = data1 or load_driver(driver1, lap1, key1)
            data2 = data2 or load_driver(driver2, lap2, key2)
        else:
            print(f"Telemetry Cache Hit for {driver1} ({lap1}) and {driver2} ({lap2})")

        d1_telemetry = data1["Telemetry"]
        d2_telemetry = data2["Telemetry"]
        delta_data = calculate_telemetry_delta(d1_telemetry, d2_telemetry)

        corners_key = f"circuit/{year}/{gp}/corners.json"
        corners = read_circuit_corners(get_json_cache(corners_key))
        if corners is None:
            try:
                if "sess" not in locals():
                    sess = fastf1.get_session(year, gp, session)
                    sess.load(weather=False, messages=False)
                corners = extract_corners_from_circuit_info(get_safe_circuit_info(sess))
                set_json_cache(corners_key, circuit_corners_payload(corners))
            except Exception as error:
                print(f"Error fetching/caching corners: {error}")
                corners = []

        return {
            "Driver1": {"Name": driver1, "Color": DRIVER_COLORS.get(driver1, "#FFFFFF"), "Telemetry": d1_telemetry, "LapTime": data1["LapTime"]},
            "Driver2": {"Name": driver2, "Color": DRIVER_COLORS.get(driver2, "#FFFFFF"), "Telemetry": d2_telemetry, "LapTime": data2["LapTime"]},
            "Delta": delta_data,
            "Corners": corners,
            "DeltaConvention": "Driver2 elapsed time - Driver1 elapsed time using FastF1-style distance scaling; positive means Driver1 is ahead.",
            "DeltaReferenceDriver": driver1,
        }
    except HTTPException:
        raise
    except ValueError as error:
        print(f"Invalid telemetry input for {key1} or {key2}: {error}")
        raise HTTPException(status_code=422, detail=f"Invalid telemetry data: {error}")
    except Exception as error:
        print(f"Telemetry error: {error}")
        raise HTTPException(status_code=500, detail=str(error))

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
        print(f"Events error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sessions")
def get_sessions(year: int, gp: str):
    try:
        event = fastf1.get_event(year, gp)
        sessions = []
        for i in range(1, 6):
            sess_name = event.get_session_name(i)
            if sess_name:
                key = SESSION_KEY_MAP.get(sess_name)
                if key:
                    sessions.append({"SessionName": sess_name, "SessionKey": key})
        return sessions
    except Exception as e:
        print(f"Sessions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/drivers")
def get_drivers(year: int, gp: str, sess_type: str):
    try:
        session = fastf1.get_session(year, gp, sess_type)
        session.load(telemetry=False, weather=False, messages=False, laps=False)
        drivers = session.results[['Abbreviation', 'FullName']]
        return [{"Name": d[2], "Driver": d[1]} for d in drivers.itertuples()]
    except Exception as e:
        print(f"Drivers error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
