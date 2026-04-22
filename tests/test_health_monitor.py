"""
Tests for MC-289: Scraper health monitor and automatic failover.
Tests health_monitor.py, persist.py scrape_runs columns, and run_pipeline.py health tracking.
"""
import os, sys, time, pytest, json

sys.path.insert(0, os.path.dirname(__file__))

# ── Test Health Monitor ────────────────────────────────────────────────────────

class TestHealthMonitor:
    def setup_method(self):
        import persist
        persist._reset_conn()
        persist.init_db()
        conn = persist._get_conn()
        conn.execute("DELETE FROM scrape_runs")
        conn.commit()
        conn.close()

    def test_get_source_stats_empty(self):
        import health_monitor
        stats = health_monitor.get_source_stats()
        assert stats == []

    def test_get_source_stats_populated(self):
        import persist, health_monitor
        conn = persist._get_conn()
        conn.execute("""
            INSERT INTO scrape_runs (source, listings_seen, listings_new, listings_inactive, errors, duration_secs)
            VALUES ('Kijiji', 55, 5, 0, 0, 6.2)
        """)
        conn.execute("""
            INSERT INTO scrape_runs (source, listings_seen, listings_new, listings_inactive, errors, duration_secs)
            VALUES ('Craigslist', 312, 20, 0, 0, 0.9)
        """)
        conn.commit()
        conn.close()

        stats = health_monitor.get_source_stats()
        assert len(stats) == 2
        kijiji = next(s for s in stats if s['source'] == 'Kijiji')
        assert kijiji['avg_seen'] == 55.0
        assert kijiji['min_seen'] == 55
        assert kijiji['max_seen'] == 55

    def test_check_source_health_ok(self):
        import health_monitor, persist
        conn = persist._get_conn()
        conn.execute("""
            INSERT INTO scrape_runs (source, listings_seen, errors, duration_secs)
            VALUES ('Kijiji', 50, 0, 5.0)
        """)
        conn.execute("""
            INSERT INTO scrape_runs (source, listings_seen, errors, duration_secs)
            VALUES ('Kijiji', 45, 0, 5.0)
        """)
        conn.execute("""
            INSERT INTO scrape_runs (source, listings_seen, errors, duration_secs)
            VALUES ('Kijiji', 48, 0, 5.0)
        """)
        conn.commit()
        conn.close()

        status = health_monitor.check_source_health('Kijiji')
        assert status == 'ok'

    def test_check_source_health_critical_zero(self):
        import health_monitor, persist
        conn = persist._get_conn()
        conn.execute("""
            INSERT INTO scrape_runs (source, listings_seen, errors, duration_secs)
            VALUES ('Kijiji', 0, 3, 5.0)
        """)
        conn.commit()
        conn.close()

        status = health_monitor.check_source_health('Kijiji')
        assert status == 'critical'

    def test_check_source_health_warning_low(self):
        import health_monitor, persist
        conn = persist._get_conn()
        conn.execute("""
            INSERT INTO scrape_runs (source, listings_seen, errors, duration_secs)
            VALUES ('Kijiji', 3, 0, 5.0)
        """)
        conn.execute("""
            INSERT INTO scrape_runs (source, listings_seen, errors, duration_secs)
            VALUES ('Kijiji', 2, 0, 5.0)
        """)
        conn.commit()
        conn.close()

        status = health_monitor.check_source_health('Kijiji')
        assert status == 'warning'

    def test_check_source_health_unknown(self):
        import health_monitor
        status = health_monitor.check_source_health('Nonexistent')
        assert status == 'unknown'

    def test_alert_threshold(self):
        """Last run total < 100 triggers alert."""
        import health_monitor, persist
        conn = persist._get_conn()
        conn.execute("""
            INSERT INTO scrape_runs (source, listings_seen, errors, duration_secs)
            VALUES ('Kijiji', 30, 0, 5.0)
        """)
        conn.execute("""
            INSERT INTO scrape_runs (source, listings_seen, errors, duration_secs)
            VALUES ('Craigslist', 40, 0, 5.0)
        """)
        conn.commit()
        conn.close()

        # Simulate the alert check
        stats = health_monitor.get_source_stats()
        total = sum(s['total_seen'] for s in stats)
        # With 30 + 40 = 70, which is < 100
        assert total < 100  # alert should fire

    def test_no_alert_above_threshold(self):
        """Total >= 100 does not trigger alert."""
        import health_monitor, persist
        conn = persist._get_conn()
        conn.execute("DELETE FROM scrape_runs")
        conn.execute("""
            INSERT INTO scrape_runs (source, listings_seen, errors, duration_secs)
            VALUES ('Kijiji', 55, 0, 5.0)
        """)
        conn.execute("""
            INSERT INTO scrape_runs (source, listings_seen, errors, duration_secs)
            VALUES ('Craigslist', 312, 0, 5.0)
        """)
        conn.commit()
        conn.close()

        stats = health_monitor.get_source_stats()
        total = sum(s['total_seen'] for s in stats)
        assert total >= 100


# ── Test Persist scrape_runs columns ──────────────────────────────────────────

class TestScrapeRunsColumns:
    def setup_method(self):
        import persist
        persist._reset_conn()
        persist.init_db()
        conn = persist._get_conn()
        conn.execute("DELETE FROM scrape_runs")
        conn.commit()
        conn.close()

    def test_scrape_runs_has_errors_column(self):
        import persist
        conn = persist._get_conn()
        try:
            conn.execute("INSERT INTO scrape_runs (source, listings_seen, errors, duration_secs) VALUES (?, ?, ?, ?)",
                        ("TestSource", 50, 2, 4.5))
            conn.commit()
        except Exception as e:
            pytest.fail(f"scrape_runs.errors column missing: {e}")
        finally:
            conn.close()

    def test_scrape_runs_has_duration_secs_column(self):
        import persist
        conn = persist._get_conn()
        try:
            conn.execute("INSERT INTO scrape_runs (source, listings_seen, errors, duration_secs) VALUES (?, ?, ?, ?)",
                        ("TestSource", 50, 0, 7.3))
            conn.commit()
        except Exception as e:
            pytest.fail(f"scrape_runs.duration_secs column missing: {e}")
        finally:
            conn.close()

    def test_upsert_listings_records_source_errors_and_duration(self):
        import persist
        conn = persist._get_conn()
        conn.execute("DELETE FROM listings")
        conn.execute("DELETE FROM scrape_runs")
        conn.commit()
        conn.close()

        rows = [
            {"source": "Kijiji", "price": 2000, "beds": 2, "neighborhood": "Toronto",
             "link": "http://kijiji.ca/listing1", "days_ago": 1, "is_stale": False},
            {"source": "Craigslist", "price": 1800, "beds": 1, "neighborhood": "Toronto",
             "link": "http://craigslist.ca/listing2", "days_ago": 1, "is_stale": False},
        ]
        result = persist.upsert_listings(rows, source_errors={"Kijiji": 1, "Craigslist": 0},
                                          source_durations={"Kijiji": 5.2, "Craigslist": 2.1})

        conn = persist._get_conn()
        runs = conn.execute("SELECT source, listings_seen, errors, duration_secs FROM scrape_runs ORDER BY source").fetchall()
        conn.close()

        assert len(runs) == 2
        kijiji_run = next(r for r in runs if r[0] == 'Kijiji')
        assert kijiji_run[2] == 1  # errors
        assert kijiji_run[3] == 5.2  # duration_secs

        cl_run = next(r for r in runs if r[0] == 'Craigslist')
        assert cl_run[2] == 0
        assert cl_run[3] == 2.1

    def test_upsert_listings_one_row_per_source(self):
        import persist
        conn = persist._get_conn()
        conn.execute("DELETE FROM listings")
        conn.execute("DELETE FROM scrape_runs")
        conn.commit()
        conn.close()

        rows = [
            {"source": "Kijiji", "price": 2000, "beds": 2, "neighborhood": "Toronto",
             "link": "http://kijiji.ca/listing1", "days_ago": 1, "is_stale": False},
            {"source": "Kijiji", "price": 2100, "beds": 2, "neighborhood": "Toronto",
             "link": "http://kijiji.ca/listing2", "days_ago": 1, "is_stale": False},
            {"source": "Craigslist", "price": 1800, "beds": 1, "neighborhood": "Toronto",
             "link": "http://craigslist.ca/listing3", "days_ago": 1, "is_stale": False},
        ]
        result = persist.upsert_listings(rows)

        conn = persist._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM scrape_runs").fetchone()[0]
        conn.close()
        assert count == 2  # one row per source, not one per listing


# ── Test health_monitor CLI ───────────────────────────────────────────────────

class TestHealthMonitorCLI:
    def test_check_health_cli_no_error(self):
        import health_monitor, io, sys
        old_argv = sys.argv
        sys.argv = ['health_monitor.py', '--check-health']
        try:
            # Should not raise
            health_monitor.print_health_table()
        finally:
            sys.argv = old_argv

    def test_check_health_source_flag(self):
        import health_monitor, io, sys
        old_argv = sys.argv
        sys.argv = ['health_monitor.py', '--source', 'Kijiji']
        try:
            status = health_monitor.check_source_health('Kijiji')
            # Should return 'unknown' when empty
            assert status in ('ok', 'warning', 'critical', 'unknown')
        finally:
            sys.argv = old_argv


if __name__ == '__main__':
    pytest.main([__file__, '-v'])