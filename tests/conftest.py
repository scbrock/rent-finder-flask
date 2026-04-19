"""
Shared pytest fixtures for rent_finder tests.
Sets RENT_DATA_DIR env var BEFORE any module imports that use it.
"""
import sys, os

# rent_finder/tests/ -> rent_finder/ -> project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENT_FINDER = PROJECT_ROOT  # 'rent_finder' dir

# Add rent_finder to sys.path so 'import app' etc. work
if RENT_FINDER not in sys.path:
    sys.path.insert(0, RENT_FINDER)

# Set default test data dir (tests can override via env var)
os.environ.setdefault('RENT_DATA_DIR', os.path.join(RENT_FINDER, 'tests', 'test_data'))
os.makedirs(os.environ['RENT_DATA_DIR'], exist_ok=True)