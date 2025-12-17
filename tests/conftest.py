"""Pytest configuration and shared fixtures."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pandas as pd
import numpy as np
import tempfile

from src.ingest.ingest_all import synthetic_area_series


@pytest.fixture
def synthetic_prices_10d():
    """Fixture: 10 days of synthetic price data."""
    return synthetic_area_series("DE", days=10)


@pytest.fixture
def synthetic_prices_30d():
    """Fixture: 30 days of synthetic price data."""
    return synthetic_area_series("DE", days=30)


@pytest.fixture
def synthetic_prices_60d():
    """Fixture: 60 days of synthetic price data."""
    return synthetic_area_series("DE", days=60)


@pytest.fixture
def synthetic_prices_365d():
    """Fixture: 365 days of synthetic price data."""
    return synthetic_area_series("DE", days=365)


@pytest.fixture
def temp_data_dir():
    """Fixture: Temporary directory for test data."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir

    # Cleanup
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_units_merit():
    """Fixture: Sample units for merit-order dispatch."""
    return [
        {"name": "wind", "pmax": 100, "cost": 0},
        {"name": "solar", "pmax": 80, "cost": 5},
        {"name": "nuclear", "pmax": 150, "cost": 10},
        {"name": "coal", "pmax": 100, "cost": 25},
        {"name": "gas", "pmax": 200, "cost": 45},
    ]


@pytest.fixture
def sample_units_uc():
    """Fixture: Sample units for UC solver."""
    return [
        {
            "name": "base",
            "pmin": 50,
            "pmax": 200,
            "cost": 30,
            "startup_cost": 500,
            "min_up": 4,
            "min_down": 2,
            "ramp_up": 100,
            "ramp_down": 100,
            "initial_status": 1,
            "initial_output": 100,
        },
        {
            "name": "peak",
            "pmin": 0,
            "pmax": 150,
            "cost": 60,
            "startup_cost": 300,
            "min_up": 1,
            "min_down": 1,
            "ramp_up": 150,
            "ramp_down": 150,
            "initial_status": 0,
            "initial_output": 0,
        },
    ]


@pytest.fixture
def sample_demand_24h():
    """Fixture: Sample 24-hour demand profile."""
    base = 250
    variation = 50 * np.sin(np.linspace(0, 2 * np.pi, 24))
    return np.maximum(base + variation, 100)


@pytest.fixture
def sample_gen_mix():
    """Fixture: Sample zonal generation mix."""
    return {"wind": 80, "solar": 40, "nuclear": 60, "hydro": 30, "gas": 100, "coal": 50}


@pytest.fixture
def sample_cost_map():
    """Fixture: Sample cost map by fuel type."""
    return {"wind": 0, "solar": 5, "hydro": 15, "nuclear": 10, "coal": 25, "gas": 45}


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line(
        "markers", "slow: mark test as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line("markers", "edge_case: mark test as an edge case test")


def pytest_collection_modifyitems(config, items):
    """Automatically mark tests."""
    for item in items:
        # Mark integration tests
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
        # Mark unit tests
        elif "test_" in item.nodeid and "integration" not in item.nodeid:
            item.add_marker(pytest.mark.unit)

        # Mark slow tests
        if "large" in item.nodeid or "365d" in item.nodeid:
            item.add_marker(pytest.mark.slow)

        # Mark edge case tests
        if "edge" in item.nodeid or "error" in item.nodeid or "corrupt" in item.nodeid:
            item.add_marker(pytest.mark.edge_case)
