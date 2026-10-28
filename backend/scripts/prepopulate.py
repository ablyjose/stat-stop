import sys
import os
import argparse
from datetime import datetime, timezone
import pandas as pd
import fastf1
from dotenv import load_dotenv

# Force stdout/stderr to use UTF-8, especially on Windows console
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        # Fallback for old python versions where reconfigure is not available
        pass

# Add backend directory to system path to import r2_client
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
from r2_client import (get_json_cache, set_json_cache, check_cache_exists, safe_float,
                       telemetry_cache_key, telemetry_completion_key,
                       TELEMETRY_CACHE_REVISION, valid_race_pace,
                       read_circuit_corners, circuit_corners_payload)
from r2_client import get_r2_client, R2_BUCKET_NAME
from telemetry import calculate_telemetry_delta, get_lap_telemetry
from fastf1.mvapi import get_circuit_info as mvapi_get_circuit_info


def extract_corners_from_circuit_info(circuit_info):
    """Extract circuit corner markers from FastF1 circuit info, skipping invalid distances."""
    corners = []
    if circuit_info is None or not hasattr(circuit_info, 'corners'):
        return corners

    try:
        for _, corner in circuit_info.corners.iterrows():
            distance_value = corner['Distance']
            if safe_float(distance_value, -1) < 0:
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
        if circuit_info is None:
            print("  Circuit provider has no map for this circuit; corner markers are unavailable.")
            return None
        
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
        raise RuntimeError("Circuit source is unavailable") from ex

def save_cache(key, data):
    if not set_json_cache(key, data):
        raise RuntimeError(f"R2 upload failed: {key}")


def prepopulate_circuit_corners(year: int, gp: str, force: bool = False):
    cache_key = f"circuit/{year}/{gp}/corners.json"

    if not force and read_circuit_corners(get_json_cache(cache_key)) is not None:
        print(f"  ✓ Circuit corners already cached ({cache_key})")
        return

    print(f"  Extracting circuit corners for {gp} ({year})...")
    # Try competitive sessions in order until one yields valid corner data
    event = fastf1.get_event(year, gp)
    names = set(event.values)
    for session_id, name in [('R', 'Race'), ('Q', 'Qualifying'), ('S', 'Sprint'), ('SQ', 'Sprint Qualifying'), ('SS', 'Sprint Shootout')]:
        if name not in names:
            continue
        try:
            sess = fastf1.get_session(year, gp, session_id)
            sess.load(weather=False, messages=False)
            # A source/authentication failure says nothing about map availability.
            # Only negative-cache maps after the circuit identity was loaded.
            sess.session_info['Meeting']['Circuit']['Key']
            circuit_info = get_safe_circuit_info(sess)
            if circuit_info is None:
                save_cache(cache_key, circuit_corners_payload([]))
                return
            corners = extract_corners_from_circuit_info(circuit_info)
            if corners:
                save_cache(cache_key, corners)
                print(f"  ✓ Saved circuit corners to R2 ({cache_key}) from session {session_id}")
                return
        except Exception as e:
            print(f"  Warning: Could not extract corners from {session_id}: {e}")
            continue

    print(f"  ⚠ Could not extract circuit corners for {gp} ({year}) from any session")

def prepopulate_session_race_pace(year: int, gp: str, session: str, force: bool = False):
    print(f"  Processing Race Pace timing index for {session}...")
    cache_key = f"timing/{year}/{gp}/{session}/laps.json"

    if not force and valid_race_pace(get_json_cache(cache_key)):
        print(f"  ✓ Race pace already cached for {session} ({cache_key})")
        return True

    try:
        sess = fastf1.get_session(year, gp, session)
        sess.load(messages=False, weather=False, telemetry=False)

        total_laps = int(sess.laps['LapNumber'].max()) if not sess.laps.empty else 0
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
                print(f"    Error processing driver {drv} race pace: {e}")
                failed_drivers.append(drv)
                
        if failed_drivers:
            raise RuntimeError(f"Incomplete lap timing for drivers: {', '.join(failed_drivers)}")
        if not valid_race_pace(full_cache_data):
            raise RuntimeError(f"No usable lap timing available for {gp} {session}")
        save_cache(cache_key, full_cache_data)
        print(f"  ✓ Saved race pace index to R2 ({cache_key})")
        return True
    except Exception as e:
        print(f"  ✗ Error prepopulating race pace: {e}")
        return False

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

def pick_telemetry_lap(driver_laps):
    """Choose a fastest lap, falling back to the first available lap."""
    if driver_laps is None or driver_laps.empty:
        return None
    fastest = driver_laps.pick_fastest()
    return fastest if fastest is not None else driver_laps.iloc[0]

def prepopulate_session_telemetry(year: int, gp: str, session: str, force: bool = False):
    print(f"  Processing Telemetry components for {session}...")
    completion_key = telemetry_completion_key(year, gp, session)

    if not force and check_cache_exists(completion_key):
        print(f"  ✓ Telemetry already cached for {session}")
        return True

    try:
        sess = fastf1.get_session(year, gp, session)
        sess.load(weather=False, messages=False)

        all_drivers = list(sess.laps['Driver'].unique()) if not sess.laps.empty else []
        if not all_drivers:
            print(f"  ⚠ No drivers found for {session}; skipping telemetry prepopulation")
            return False

        invalid_drivers = []
        
        for drv in all_drivers:
            cache_key = telemetry_cache_key(year, gp, session, drv, "fastest")
            if not force:
                cached = get_json_cache(cache_key)
                try:
                    if isinstance(cached, dict) and 'LapTime' in cached:
                        calculate_telemetry_delta(cached.get('Telemetry'), cached.get('Telemetry'))
                        continue
                except ValueError:
                    pass

            try:
                d_laps = sess.laps.pick_drivers(drv)
                if d_laps.empty:
                    invalid_drivers.append(drv)
                    continue
                lap_d = pick_telemetry_lap(d_laps)

                tel = get_lap_telemetry(lap_d)
                if tel.empty:
                    invalid_drivers.append(drv)
                    continue

                tel_data = []
                for i in range(len(tel)):
                    tel_data.append({
                        "Distance": float(tel['Distance'].iloc[i]),
                        "Speed": safe_float(tel['Speed'].iloc[i]),
                        "Throttle": safe_float(tel['Throttle'].iloc[i]),
                        "Brake": safe_float(tel['Brake'].iloc[i]),
                        "RPM": safe_float(tel['RPM'].iloc[i]),
                        "nGear": int(tel['nGear'].iloc[i]) if not pd.isna(tel['nGear'].iloc[i]) else 0,
                        "DRS": int(tel['DRS'].iloc[i]) if not pd.isna(tel['DRS'].iloc[i]) else 0,
                        "Time": float(tel['Time'].iloc[i].total_seconds())
                    })

                calculate_telemetry_delta(tel_data, tel_data)
                d_cache = {
                    "Driver": drv,
                    "LapNumber": "fastest",
                    "LapTime": extract_lap_time(lap_d),
                    "Telemetry": tel_data
                }
                save_cache(cache_key, d_cache)
            except Exception as error:
                print(f"    Telemetry failed for {drv}: {error}")
                invalid_drivers.append(drv)
                continue

        if invalid_drivers:
            print(f"  ⚠ Telemetry remains uncached for {len(invalid_drivers)} driver(s) in {session}")
            return False

        save_cache(completion_key, {
            "CacheVersion": TELEMETRY_CACHE_REVISION,
            "Drivers": all_drivers
        })
        print(f"  ✓ Cached telemetry for drivers in {session}")
        return True

    except Exception as e:
        print(f"  ✗ Error prepopulating telemetry: {e}")
        return False

def prepopulate_gp(year: int, gp: str, force: bool = False):
    print(f"\nPre-populating GP: {gp} ({year})...")

    try:
        event = fastf1.get_event(year, gp)
    except Exception as error:
        print(f"  Error fetching event: {error}")
        return False
    gp = event.get('EventName', gp)

    # Corner maps are optional annotations supplied by a separate provider.
    try:
        prepopulate_circuit_corners(year, gp, force=force)
    except Exception as error:
        print(f"  Warning: Optional corner annotations unavailable: {error}")
    available_sessions = set(event.values if hasattr(event, "values") else event)

    success = True
    for session, event_name in [('S', 'Sprint'), ('R', 'Race')]:
        if event_name in available_sessions:
            pace_ok = prepopulate_session_race_pace(year, gp, session, force=force)
            telemetry_ok = prepopulate_session_telemetry(year, gp, session, force=force)
            success = pace_ok and telemetry_ok and success

    for session, event_name in [('SQ', 'Sprint Qualifying'), ('SS', 'Sprint Shootout'), ('Q', 'Qualifying')]:
        if event_name in available_sessions:
            success = prepopulate_session_telemetry(year, gp, session, force=force) and success
    return bool(success)

def main():
    parser = argparse.ArgumentParser(description="Prepopulate Cloudflare R2 cache with FastF1 timing and telemetry data.")
    parser.add_argument("--year", type=int, default=datetime.now(timezone.utc).year, help="F1 season year (default: current year)")
    parser.add_argument("--gp", type=str, default=None, help="GP Event Name (e.g. Monaco, Brazil) - if omitted, caches all GPs in the season")
    parser.add_argument("--force", action="store_true", help="Rebuild existing R2 entries")
    
    args = parser.parse_args()

    client = get_r2_client()
    if client is None:
        print("R2 is unavailable. Configure the four R2 settings in backend/.env or the environment.")
        return 1
    try:
        client.head_bucket(Bucket=R2_BUCKET_NAME)
    except Exception as error:
        print(f"R2 bucket access failed: {error}")
        return 1
    
    # Enable FastF1 local caching to speed up local processing
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    fastf1.Cache.configure(cache_dir=cache_dir)
    
    if args.gp:
        return 0 if prepopulate_gp(args.year, args.gp, force=args.force) else 1
    else:
        print(f"Pre-populating entire F1 season: {args.year}")
        try:
            schedule = fastf1.get_event_schedule(args.year)
            success = True
            for i, row in schedule.iterrows():
                if row['RoundNumber'] == 0:
                    continue
                event_date = pd.to_datetime(row['EventDate'], utc=True)
                if pd.isna(event_date) or event_date.date() >= datetime.now(timezone.utc).date():
                    continue
                gp_name = row['EventName']
                success = prepopulate_gp(args.year, gp_name, force=args.force) and success
            return 0 if success else 1
        except Exception as e:
            print(f"Error fetching event schedule for season {args.year}: {e}")
            return 1

if __name__ == "__main__":
    sys.exit(main())
        except Exception as e:
            print(f"Error fetching event schedule for season {args.year}: {e}")
            return 1

if __name__ == "__main__":
    sys.exit(main())
