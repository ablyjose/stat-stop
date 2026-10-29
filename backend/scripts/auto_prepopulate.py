"""Populate concluded weekends once, or poll with --watch. All times are UTC."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import time

import fastf1
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))
from r2_client import check_cache_exists, get_r2_client, R2_BUCKET_NAME, telemetry_completion_key

SESSION_NAMES = {
    'Race': 'R', 'Qualifying': 'Q', 'Sprint': 'S',
    'Sprint Qualifying': 'SQ', 'Sprint Shootout': 'SS',
}


def event_sessions(event):
    return [SESSION_NAMES[event.get(f'Session{i}')]
            for i in range(1, 6) if event.get(f'Session{i}') in SESSION_NAMES]


def check_is_prepopulated(year, gp, sessions=None):
    """Check race timing, circuit annotations, and the event's telemetry sessions.

    Use the shared revision helper so scheduler and importer agree on keys.
    Storage access errors propagate instead of being treated as cache misses.
    """
    for key in (f'timing/{year}/{gp}/R/laps.json', f'circuit/{year}/{gp}/corners.json'):
        if not check_cache_exists(key):
            print(f'  Missing cache entry: {key}', flush=True)
            return False
    if sessions is None:
        sessions = event_sessions(fastf1.get_event(year, gp))
    for session in sessions:
        key = telemetry_completion_key(year, gp, session)
        if not check_cache_exists(key):
            print(f'  Missing cache entry: {key}', flush=True)
            return False
    return True


def run_prepopulate_gp(year, gp, force=False):
    command = [sys.executable, '-u', str(SCRIPT_DIR / 'prepopulate.py'),
               '--year', str(year), '--gp', gp]
    if force:
        command.append('--force')
    print(f'[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S UTC}] Populating {gp} ({year})...', flush=True)
    # Closing stdin prevents background jobs from waiting on a login prompt.
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          stdin=subprocess.DEVNULL, text=True, encoding='utf-8',
                          errors='replace', cwd=SCRIPT_DIR.parent.parent) as child:
        for line in child.stdout:
            print(line, end='', flush=True)
        return child.wait() == 0


def run_prepopulate_with_retries(year, gp, force=False, attempts=1, retry_delay=900):
    for attempt in range(1, attempts + 1):
        print(f'\n--- Attempt {attempt}/{attempts} for {gp} ({year}) ---', flush=True)
        try:
            if run_prepopulate_gp(year, gp, force=force):
                if check_is_prepopulated(year, gp):
                    print(f'✓ Successfully prepopulated {gp} ({year})', flush=True)
                    return True
                print(f'  Import finished, but required cache entries are still missing for {gp}.', flush=True)
        except OSError as error:
            print(f'Could not run prepopulation: {error}', flush=True)
        if attempt < attempts:
            print(f'Population failed; retrying in {retry_delay:g} seconds.', flush=True)
            time.sleep(retry_delay)
    print(f'✗ Failed to prepopulate {gp} ({year}) after {attempts} attempts.', flush=True)
    return False


def run_schedule(year, force=False, attempts=1, retry_delay=900,
                 csv_path=SCRIPT_DIR / 'f1_race_ends.csv', now=None):
    now = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if now.tzinfo is None:
        now = now.tz_localize('UTC')
    print(f'Fetching F1 schedule for season {year}...', flush=True)
    schedule = fastf1.get_event_schedule(year)
    events = []
    for _, event in schedule.iterrows():
        if event.get('RoundNumber', 0) == 0:
            continue
        race_slot = next((i for i in range(1, 6) if event.get(f'Session{i}') == 'Race'), None)
        start = pd.to_datetime(event.get(f'Session{race_slot}DateUtc'), utc=True) if race_slot else pd.NaT
        end = start + pd.Timedelta(hours=2.5)
        events.append((event, start, end))
    concluded = sum(pd.notna(end) and end <= now for _, _, end in events)
    print(f'\nChecking {concluded} concluded races in season {year}...', flush=True)
    rows = []
    success = True
    attempted_import = False
    for event, start, end in events:
        gp = event['EventName']
        populated = False
        status = 'SCHEDULE_UNKNOWN' if pd.isna(end) else 'UPCOMING'
        if pd.notna(end) and end <= now:
            sessions = event_sessions(event)
            populated = check_is_prepopulated(year, gp, sessions)
            if populated and not force:
                print(f'  ✓ {gp} ({year}) already prepopulated in R2.', flush=True)
            else:
                attempted_import = True
                reason = 'Force requested' if force else 'Not cached in R2'
                print(f'\n🏁 Race weekend ended for {gp} (Estimated end: {end}). Reason: {reason}.', flush=True)
                populated = run_prepopulate_with_retries(
                    year, gp, force=force, attempts=attempts, retry_delay=retry_delay)
                # Confirm the race index before reporting a completed weekend.
                populated = populated and check_is_prepopulated(year, gp, sessions)
            status = 'PREPOPULATED' if populated else 'FAILED'
            success = populated and success
        rows.append({
            'RoundNumber': event['RoundNumber'], 'Year': year, 'EventName': gp,
            'OfficialEventName': event.get('OfficialEventName', ''),
            'Country': event.get('Country', ''), 'Location': event.get('Location', ''),
            'RaceStartUtc': '' if pd.isna(start) else start.strftime('%Y-%m-%d %H:%M:%S UTC'),
            'EstimatedRaceEndUtc': '' if pd.isna(end) else end.strftime('%Y-%m-%d %H:%M:%S UTC'),
            'Prepopulated': populated, 'Status': status,
        })
    csv_path = Path(csv_path)
    show_csv_status = attempted_import or not csv_path.exists()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    if show_csv_status:
        print(f'✓ Saved race schedule status to CSV: {csv_path}', flush=True)
    return success


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument('--gp', help='Populate one event instead of checking the season')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--watch', action='store_true', help='Repeat the season check until stopped')
    parser.add_argument('--interval', type=float, default=3600, help='Seconds between season checks')
    parser.add_argument('--attempts', type=int, default=1,
                        help='Attempts per race; set above 1 to enable retry waits (default: 1)')
    parser.add_argument('--retry-delay', type=float, default=900, help='Seconds between retries')
    parser.add_argument('--log-file', default=str(SCRIPT_DIR / 'auto_prepopulate.log'),
                        help='Append output to this log file')
    args = parser.parse_args()
    if args.attempts < 1 or args.retry_delay < 0 or args.interval <= 0:
        parser.error('Attempts and interval must be positive; retry delay must be nonnegative.')
    cache_dir = SCRIPT_DIR.parent.parent / 'cache'
    cache_dir.mkdir(exist_ok=True)
    fastf1.Cache.configure(cache_dir=str(cache_dir))
    if args.gp:
        if not args.force and check_is_prepopulated(args.year, args.gp):
            print(f'  ✓ {args.gp} ({args.year}) already prepopulated in R2.', flush=True)
            return 0
        return 0 if run_prepopulate_with_retries(
            args.year, args.gp, force=args.force, attempts=args.attempts,
            retry_delay=args.retry_delay) else 1
    client = get_r2_client()
    if client is None:
        print('Configure R2 credentials before running the scheduler.')
        return 1
    try:
        client.head_bucket(Bucket=R2_BUCKET_NAME)
    except Exception as error:
        print(f'R2 bucket access failed: {error}')
        return 1
    while True:
        try:
            success = run_schedule(args.year, args.force, args.attempts, args.retry_delay)
        except Exception as error:
            print(f'Schedule check failed: {error}', flush=True)
            success = False
        if not args.watch:
            return 0 if success else 1
        time.sleep(args.interval)


class Tee:
    def __init__(self, console, log):
        self.console, self.log = console, log

    def write(self, text):
        if self.console is not None:
            self.console.write(text)
        return self.log.write(text)

    def flush(self):
        if self.console is not None:
            self.console.flush()
        self.log.flush()


if __name__ == '__main__':
    if sys.platform == 'win32':
        for stream in (sys.stdout, sys.stderr):
            if stream is not None:
                stream.reconfigure(encoding='utf-8')
    if '--help' in sys.argv or '-h' in sys.argv:
        sys.exit(main())
    log_parser = argparse.ArgumentParser(add_help=False)
    log_parser.add_argument('--log-file', default=str(SCRIPT_DIR / 'auto_prepopulate.log'))
    log_args, _ = log_parser.parse_known_args()
    log_path = Path(log_args.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a', encoding='utf-8', buffering=1) as log:
        with redirect_stdout(Tee(sys.stdout, log)), redirect_stderr(Tee(sys.stderr, log)):
            try:
                sys.exit(main())
            except KeyboardInterrupt:
                print('Scheduler stopped.')
                sys.exit(130)
