import sys
import os
import argparse
import pandas as pd
import fastf1

# Add backend directory to system path to import r2_client
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from r2_client import get_json_cache, set_json_cache

def prepopulate_session_race_pace(year: int, gp: str, session: str):
    print(f"  Processing Race Pace timing index for {session}...")
    cache_key = f"timing/{year}/{gp}/{session}/laps.json"
    
    try:
        sess = fastf1.get_session(year, gp, session)
        sess.load(messages=False, weather=False, telemetry=False)
        
        total_laps = int(sess.laps['LapNumber'].max()) if not sess.laps.empty else 0
        all_drivers = list(sess.laps['Driver'].unique()) if not sess.laps.empty else []
        
        corners = []
        circuit_info = sess.get_circuit_info()
        if circuit_info is not None:
            for _, corner in circuit_info.corners.iterrows():
                corners.append({
                    "Number": int(corner['Number']),
                    "Distance": float(corner['Distance']),
                    "Letter": corner['Letter'] if not pd.isna(corner['Letter']) else ""
                })
                
        full_cache_data = {
            "TotalLaps": total_laps,
            "Corners": corners,
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
                print(f"    Error processing driver {drv} race pace: {e}")
                
        set_json_cache(cache_key, full_cache_data)
        print(f"  ✓ Saved race pace index to R2 ({cache_key})")
        return corners
    except Exception as e:
        print(f"  ✗ Error prepopulating race pace: {e}")
        return []

def prepopulate_session_telemetry(year: int, gp: str, session: str, corners=None):
    print(f"  Processing Telemetry components for {session}...")
    try:
        sess = fastf1.get_session(year, gp, session)
        sess.load(weather=False, messages=False)
        
        all_drivers = list(sess.laps['Driver'].unique()) if not sess.laps.empty else []
        
        for drv in all_drivers:
            try:
                # Cache fastest lap
                d_laps = sess.laps.pick_drivers(drv)
                if d_laps.empty:
                    continue
                
                lap_d = d_laps.pick_fastest()
                if pd.isna(lap_d['LapTime']):
                    continue
                
                tel = lap_d.get_telemetry().add_distance()
                if tel.empty:
                    continue
                
                tel_data = []
                for i in range(len(tel)):
                    tel_data.append({
                        "Distance": float(tel['Distance'].iloc[i]),
                        "Speed": float(tel['Speed'].iloc[i]),
                        "Throttle": float(tel['Throttle'].iloc[i]),
                        "Brake": float(tel['Brake'].iloc[i]),
                        "RPM": float(tel['RPM'].iloc[i]),
                        "nGear": int(tel['nGear'].iloc[i]),
                        "DRS": int(tel['DRS'].iloc[i]),
                        "Time": float(tel['Time'].iloc[i].total_seconds())
                    })
                
                cache_key = f"telemetry/{year}/{gp}/{session}/{drv}_fastest.json"
                d_cache = {
                    "Driver": drv,
                    "LapNumber": "fastest",
                    "LapTime": float(lap_d['LapTime'].total_seconds()),
                    "Telemetry": tel_data
                }
                set_json_cache(cache_key, d_cache)
            except Exception as e:
                # Expected if telemetry fails to load for a specific driver
                continue
                
        print(f"  ✓ Cached telemetry for drivers in {session}")
        
        # Save corners to timing file if they were extracted
        if corners:
            try:
                session_key = f"timing/{year}/{gp}/{session}/laps.json"
                session_data = get_json_cache(session_key)
                if session_data:
                    session_data["Corners"] = corners
                    set_json_cache(session_key, session_data)
            except Exception as e:
                print(f"  Warning: Could not write corners to timing index: {e}")
                
    except Exception as e:
        print(f"  ✗ Error prepopulating telemetry: {e}")

def prepopulate_gp(year: int, gp: str):
    print(f"\nPre-populating GP: {gp} ({year})...")
    # Quali and Race sessions are the primary ones
    for session in ['Q', 'R']:
        corners = prepopulate_session_race_pace(year, gp, session)
        prepopulate_session_telemetry(year, gp, session, corners)

def main():
    parser = argparse.ArgumentParser(description="Prepopulate Cloudflare R2 cache with FastF1 timing and telemetry data.")
    parser.add_argument("--year", type=int, default=2024, help="F1 Season Year (default: 2024)")
    parser.add_argument("--gp", type=str, default=None, help="GP Event Name (e.g. Monaco, Brazil) - if omitted, caches all GPs in the season")
    
    args = parser.parse_args()
    
    # Enable FastF1 local caching to speed up local processing
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cache')
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
    fastf1.Cache.enable_cache(cache_dir)
    
    if args.gp:
        prepopulate_gp(args.year, args.gp)
    else:
        print(f"Pre-populating entire F1 season: {args.year}")
        try:
            schedule = fastf1.get_event_schedule(args.year)
            for i, row in schedule.iterrows():
                if "Test" in row['EventName']:
                    continue
                gp_name = row['EventName']
                prepopulate_gp(args.year, gp_name)
        except Exception as e:
            print(f"Error fetching event schedule for season {args.year}: {e}")

if __name__ == "__main__":
    main()
