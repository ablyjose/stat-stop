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
                
                color = DRIVER_COLORS.get(drv, '#FFFFFF')
                
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
