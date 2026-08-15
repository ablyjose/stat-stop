import sys
import os
import argparse
import pandas as pd
import fastf1

# Force stdout/stderr to use UTF-8, especially on Windows console
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        # Fallback for old python versions where reconfigure is not available
        pass

# Add backend directory to system path to import r2_client
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from r2_client import get_json_cache, set_json_cache, check_cache_exists, safe_float
from fastf1.mvapi import get_circuit_info as mvapi_get_circuit_info


def extract_corners_from_circuit_info(circuit_info):
    """Extract circuit corner markers from FastF1 circuit info, skipping invalid distances."""
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
        print(f"  Warning: Could not extract circuit info corners: {ce}")

    return corners

def get_safe_circuit_info(sess):
    """Safely fetch circuit info, falling back to other drivers/laps if the fastest lap telemetry is missing."""
    try:
        # Try default FastF1 method first
        return sess.get_circuit_info()
    except Exception as e:
        print(f"  Warning: Default get_circuit_info failed: {e}. Attempting fallback...")
        
    try:
        c_key = sess.session_info['Meeting']['Circuit']['Key']
        circuit_info = mvapi_get_circuit_info(year=sess.event.year, circuit_key=c_key)
        
        # Search for any lap in the session that has valid telemetry
        for _, lap in sess.laps.iterrows():
            try:
                tel = lap.get_telemetry()
                if tel is not None and not tel.empty and 'Distance' in tel.columns:
                    circuit_info.add_marker_distance(reference_lap=lap)
                    print(f"  ✓ Re-mapped corners using fallback reference lap from driver {lap['Driver']} (Lap {lap['LapNumber']})")
                    return circuit_info
            except Exception:
                continue
                
        print("  Warning: No laps with valid telemetry found. Returning corners without distance markers.")
        return circuit_info
    except Exception as ex:
        print(f"  Error in get_safe_circuit_info fallback: {ex}")
        return None

def prepopulate_circuit_corners(year: int, gp: str):
    cache_key = f"circuit/{year}/{gp}/corners.json"

    if check_cache_exists(cache_key):
        print(f"  ✓ Circuit corners already cached ({cache_key})")
        return

    print(f"  Extracting circuit corners for {gp} ({year})...")
    # Try competitive sessions in order until one yields valid corner data
    for session_id in ['R', 'Q', 'S', 'SQ']:
        try:
            sess = fastf1.get_session(year, gp, session_id)
            sess.load(weather=False, messages=False)
            circuit_info = get_safe_circuit_info(sess)
            corners = extract_corners_from_circuit_info(circuit_info)
            if corners:
                set_json_cache(cache_key, corners)
                print(f"  ✓ Saved circuit corners to R2 ({cache_key}) from session {session_id}")
                return
        except Exception as e:
            print(f"  Warning: Could not extract corners from {session_id}: {e}")
            continue

    print(f"  ⚠ Could not extract circuit corners for {gp} ({year}) from any session")

def prepopulate_session_race_pace(year: int, gp: str, session: str):
    print(f"  Processing Race Pace timing index for {session}...")
    cache_key = f"timing/{year}/{gp}/{session}/laps.json"

    if check_cache_exists(cache_key):
        print(f"  ✓ Race pace already cached for {session} ({cache_key})")
        return []

    try:
        sess = fastf1.get_session(year, gp, session)
        sess.load(messages=False, weather=False, telemetry=False)

        total_laps = int(sess.laps['LapNumber'].max()) if not sess.laps.empty else 0
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
                print(f"    Error processing driver {drv} race pace: {e}")
                
        set_json_cache(cache_key, full_cache_data)
        print(f"  ✓ Saved race pace index to R2 ({cache_key})")
        return []
    except Exception as e:
        print(f"  ✗ Error prepopulating race pace: {e}")
        return []

def extract_lap_time(lap):
    """Safely extract float seconds for a lap time without raising ValueError or TypeErrors."""
    if lap is None:
        return None
    try:
        if isinstance(lap, pd.DataFrame):
            if lap.empty:
                return None
            val = lap['LapTime'].iloc[0]
        elif hasattr(lap, '__getitem__') or isinstance(lap, pd.Series):
            val = lap['LapTime']
        else:
            val = getattr(lap, 'LapTime', None)

        if pd.notna(val) and hasattr(val, 'total_seconds'):
            return float(val.total_seconds())
    except Exception:
        return None
    return None

def prepopulate_session_telemetry(year: int, gp: str, session: str):
    print(f"  Processing Telemetry components for {session}...")
    completion_key = f"telemetry/{year}/{gp}/{session}/_complete-v1.json"

    if check_cache_exists(completion_key):
        print(f"  ✓ Telemetry already cached for {session}")
        return

    try:
        sess = fastf1.get_session(year, gp, session)
        sess.load(weather=False, messages=False)

        all_drivers = list(sess.laps['Driver'].unique()) if not sess.laps.empty else []
        if not all_drivers:
            print(f"  ⚠ No drivers found for {session}; skipping telemetry prepopulation")
            return

        invalid_drivers = []
        
        for drv in all_drivers:
            cache_key = f"telemetry/{year}/{gp}/{session}/{drv}_fastest.json"
            if check_cache_exists(cache_key):
                continue

            try:
                d_laps = sess.laps.pick_drivers(drv)
                if d_laps.empty:
                    invalid_drivers.append(drv)
                    continue

                lap_d = d_laps.pick_fastest() if len(d_laps) >= 2 else None
                if lap_d is None or (isinstance(lap_d, (pd.Series, pd.DataFrame)) and lap_d.empty):
                    lap_d = d_laps.pick_laps(1) if not d_laps.pick_laps(1).empty else d_laps.iloc[0]

                tel = lap_d.get_telemetry().add_distance()
                if tel.empty:
                    invalid_drivers.append(drv)
                    continue

                tel_data = []
                for i in range(len(tel)):
                    tel_data.append({
                        "Distance": safe_float(tel['Distance'].iloc[i]),
                        "Speed": safe_float(tel['Speed'].iloc[i]),
                        "Throttle": safe_float(tel['Throttle'].iloc[i]),
                        "Brake": safe_float(tel['Brake'].iloc[i]),
                        "RPM": safe_float(tel['RPM'].iloc[i]),
                        "nGear": int(tel['nGear'].iloc[i]) if not pd.isna(tel['nGear'].iloc[i]) else 0,
                        "DRS": int(tel['DRS'].iloc[i]) if not pd.isna(tel['DRS'].iloc[i]) else 0,
                        "Time": safe_float(tel['Time'].iloc[i].total_seconds())
                    })

                d_cache = {
                    "Driver": drv,
                    "LapNumber": "fastest",
                    "LapTime": extract_lap_time(lap_d),
                    "Telemetry": tel_data
                }
                set_json_cache(cache_key, d_cache)
            except Exception:
                invalid_drivers.append(drv)
                continue

        if invalid_drivers:
            print(f"  ⚠ Telemetry remains uncached for {len(invalid_drivers)} driver(s) in {session}")

        set_json_cache(completion_key, {
            "CacheVersion": 1,
            "Drivers": all_drivers
        })
        print(f"  ✓ Cached telemetry for drivers in {session}")

    except Exception as e:
        print(f"  ✗ Error prepopulating telemetry: {e}")

def prepopulate_gp(year: int, gp: str):
    print(f"\nPre-populating GP: {gp} ({year})...")

    prepopulate_circuit_corners(year, gp)

    for session in ['S', 'R']:
        prepopulate_session_race_pace(year, gp, session)
        prepopulate_session_telemetry(year, gp, session)

    for session in ['SQ', 'Q']:
        prepopulate_session_telemetry(year, gp, session)

def main():
    parser = argparse.ArgumentParser(description="Prepopulate Cloudflare R2 cache with FastF1 timing and telemetry data.")
    parser.add_argument("--year", type=int, default=2024, help="F1 Season Year (default: 2024)")
    parser.add_argument("--gp", type=str, default=None, help="GP Event Name (e.g. Monaco, Brazil) - if omitted, caches all GPs in the season")
    
    args = parser.parse_args()
    
    # Enable FastF1 local caching to speed up local processing
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'cache')
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
