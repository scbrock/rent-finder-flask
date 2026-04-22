"""
Health monitor for scraper pipeline (MC-289).
Tracks source health per run, triggers alerts when listings drop below threshold.
"""
import os, sys, warnings
warnings.filterwarnings('ignore')
os.chdir(r'C:\Users\steph\.openclaw\workspace-coding\rent_finder')
import persist
from datetime import datetime, timedelta, timezone

ALERT_THRESHOLD = 100  # fire alert if total collected < this


def get_last_runs(limit=10):
    """Return last N scrape runs per source."""
    conn = persist._get_conn()
    cur = conn.execute("""
        SELECT run_id, run_ts, source, listings_seen, listings_new, listings_inactive,
               errors, duration_secs
        FROM scrape_runs
        ORDER BY run_ts DESC
        LIMIT ?
    """, (limit,))
    cols = ['run_id','run_ts','source','listings_seen','listings_new','listings_inactive',
            'errors','duration_secs']
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_source_stats():
    """Aggregate stats per source from last 7 days."""
    conn = persist._get_conn()
    cur = conn.execute("""
        SELECT
            source,
            COUNT(*) as runs,
            SUM(listings_seen) as total_seen,
            AVG(listings_seen) as avg_seen,
            MIN(listings_seen) as min_seen,
            MAX(listings_seen) as max_seen,
            SUM(errors) as total_errors,
            AVG(duration_secs) as avg_duration
        FROM scrape_runs
        WHERE run_ts >= ?
        GROUP BY source
    """, ((datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ'),))
    cols = ['source','runs','total_seen','avg_seen','min_seen','max_seen','total_errors','avg_duration']
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def print_health_table():
    """Print human-readable health status."""
    stats = get_source_stats()
    if not stats:
        print("No scrape runs recorded yet.")
        return

    print(f"{'SOURCE':<12} {'RUNS':>5} {'AVG/Run':>9} {'MIN':>6} {'MAX':>6} {'TOTAL':>7} {'AVG_ERR':>8} {'AVG_DUR':>9}")
    print("-" * 75)
    total_avg = 0
    for s in stats:
        avg_dur = f"{s['avg_duration']:.1f}s" if s['avg_duration'] else "N/A"
        print(f"{s['source']:<12} {s['runs']:>5} {s['avg_seen']:>9.1f} {s['min_seen']:>6} "
              f"{s['max_seen']:>6} {s['total_seen']:>7} {s['total_errors']:>8} {avg_dur:>9}")
        total_avg += s['avg_seen']
    
    print("-" * 75)
    print(f"Overall avg listings/run: {total_avg/len(stats):.1f}")
    
    # Alert check
    last_runs = get_last_runs(limit=2)
    if last_runs:
        total_last = sum(r['listings_seen'] for r in last_runs)
        print(f"\nLast run total: {total_last} listings")
        if total_last < ALERT_THRESHOLD:
            print(f"⚠️  ALERT: Total listings ({total_last}) below threshold ({ALERT_THRESHOLD})")


def check_source_health(source):
    """Return health status for a source: 'ok' | 'warning' | 'critical' | 'unknown'."""
    conn = persist._get_conn()
    cur = conn.execute("""
        SELECT listings_seen, errors
        FROM scrape_runs
        WHERE source = ?
        ORDER BY run_ts DESC
        LIMIT 3
    """, (source,))
    rows = cur.fetchall()
    if not rows:
        return 'unknown'
    avg_seen = sum(r[0] for r in rows) / len(rows)
    total_errors = sum(r[1] for r in rows)
    if avg_seen == 0:
        return 'critical'
    if total_errors > len(rows) * 2:
        return 'warning'
    if avg_seen < 10:
        return 'warning'
    return 'ok'


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-health', action='store_true', help='Run diagnostics')
    parser.add_argument('--source', type=str, help='Check specific source')
    args = parser.parse_args()

    if args.checkHealth or (len(sys.argv) == 2 and sys.argv[1] == '--check-health'):
        print_health_table()
    elif args.source:
        status = check_source_health(args.source)
        print(f"{args.source}: {status}")
    else:
        print_health_table()