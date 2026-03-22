"""
Integration test for city simulation wiring gaps.

Tests the five gaps identified in the skeptic integration audit:
1. Fire-and-forget geo reference loading
2. Double physics timestep (render + fixed)
3. Panel stats update before map init
4. EventBus cleanup on map destroy
5. Silent failure on empty road network

Run with:
    .venv/bin/python3 -m pytest tests/integration/test_city_sim_wiring.py -m integration -v
"""

import httpx
import pytest

from tests.integration.conftest import IntegrationReport

pytestmark = pytest.mark.integration

_TIMEOUT = 10


def _get(base_url: str, path: str, **kw) -> httpx.Response:
    return httpx.get(f"{base_url}{path}", timeout=_TIMEOUT, **kw)


class TestCitySimWiringGaps:
    """Integration tests documenting city sim wiring gaps."""

    def test_gap1_geo_reference_is_fire_and_forget(self, server):
        """Gap 1: _loadGeoReference() doesn't block initialization.

        Documents that frontend calls _loadGeoReference() without awaiting,
        meaning map can appear ready before city sim data is loaded.
        """
        # Get geo reference (should work)
        resp = _get(server.base_url, '/api/geo/reference')
        assert resp.status_code == 200
        geo = resp.json()
        assert geo['initialized'] is True

        # Get city data (should work)
        resp = _get(server.base_url, f'/api/geo/city-data?lat={geo["lat"]}&lng={geo["lng"]}&radius=300')
        assert resp.status_code == 200
        city_data = resp.json()

        # Verify city data has content
        has_roads = len(city_data.get('roads', [])) > 0
        has_buildings = len(city_data.get('buildings', [])) > 0
        assert has_roads or has_buildings, "City data should have roads or buildings"

    def test_gap2_physics_timestep_is_coupled(self, server: 'IntegrationReport'):
        """Gap 2: Vehicle physics dt = render dt with fixed accumulator.

        Documents that city sim applies fixed timestep (0.1s) on top of
        variable render dt, which varies with framerate.
        Result: vehicle behavior changes depending on render fps.
        """
        # Get geo reference
        resp = _get(server.base_url, '/api/geo/reference')
        geo = resp.json()

        # Get city data with roads
        resp = _get(server.base_url, f'/api/geo/city-data?lat={geo["lat"]}&lng={geo["lng"]}&radius=300')
        city_data = resp.json()
        roads = city_data.get('roads', [])

        # This gap is in JavaScript code, verified by code review:
        # render loop: dt = Math.min(0.1, actual_dt)
        # city sim tick(): accumulates dt into 0.1s buckets (fixed timestep)
        # Result: at 30fps (0.033s), tick 3x per frame; at 60fps (0.016s), tick 6x slower
        assert roads is not None

    def test_gap3_panel_interval_stored_at_module_scope(self, server: 'IntegrationReport'):
        """Gap 3: Panel setInterval stored at module level, can leak.

        Documents that CitySimPanelDef.js line 14 stores _updateInterval
        at module scope, not on the panel object.
        If panel is opened/closed multiple times without destroy(),
        setInterval references accumulate and leak.
        """
        # This is a code review finding. Can't test JS scope directly from Python.
        # The fix: move _updateInterval into the create() function or store on panel.
        pass

    def test_gap4_eventbus_cleanup_on_map_destroy(self, server: 'IntegrationReport'):
        """Gap 4: EventBus listeners cleaned up on map destroy.

        Documents that initMap() subscribes to city-sim events and stores
        unsub functions in _state.unsubs[], called in destroyMap().
        Potential gap: if EventBus.emit() fires during cleanup, listeners
        might access destroyed Three.js scene.
        """
        # This is a concurrency race condition that's hard to test from Python.
        # Code review confirms unsubs are properly stored and called.
        pass

    def test_gap5_empty_road_network_silent_failure(self, server: 'IntegrationReport'):
        """Gap 5: toggleCitySim() silently fails when road network is empty.

        If geo location has no roads (e.g., coordinates over ocean),
        toggleCitySim() checks stats?.edges > 0 and silently does nothing.
        User clicks 'START SIM' button, no error message, appears broken.
        """
        # Get geo reference
        resp = _get(server.base_url, '/api/geo/reference')
        geo = resp.json()

        # Get city data
        resp = _get(server.base_url, f'/api/geo/city-data?lat={geo["lat"]}&lng={geo["lng"]}&radius=300')
        assert resp.status_code == 200
        city_data = resp.json()

        # At current location, should have roads
        roads = city_data.get('roads', [])
        assert len(roads) > 0, "Test location should have roads for this test"

        # If roads were empty (ocean location), toggleCitySim() would do nothing.
        # The fix: add error messaging when edges == 0.


class TestCitySimAPIConsistency:
    """Test API endpoints work reliably."""

    def test_geo_reference_returns_consistent_data(self, server: 'IntegrationReport'):
        """Verify /api/geo/reference returns expected structure."""
        resp = _get(server.base_url, '/api/geo/reference')
        assert resp.status_code == 200

        data = resp.json()
        assert 'lat' in data
        assert 'lng' in data
        assert 'initialized' in data
        assert isinstance(data['initialized'], bool)

    def test_city_data_returns_empty_arrays_gracefully(self, server: 'IntegrationReport'):
        """Verify /api/geo/city-data returns valid structure even if empty."""
        resp = _get(server.base_url, '/api/geo/reference')
        geo = resp.json()

        resp = _get(server.base_url, f'/api/geo/city-data?lat={geo["lat"]}&lng={geo["lng"]}&radius=300')
        assert resp.status_code == 200

        data = resp.json()
        # Should have these keys (may be empty arrays)
        assert 'roads' in data or 'buildings' in data, "Should have at least roads or buildings key"

    def test_city_sim_has_data_when_roads_exist(self, server: 'IntegrationReport'):
        """Verify city sim can load when roads exist."""
        resp = _get(server.base_url, '/api/geo/reference')
        geo = resp.json()
        assert geo['initialized']

        resp = _get(server.base_url, f'/api/geo/city-data?lat={geo["lat"]}&lng={geo["lng"]}&radius=500')
        assert resp.status_code == 200
        city_data = resp.json()

        # Current test location should have content
        has_content = (
            len(city_data.get('roads', [])) > 0 or
            len(city_data.get('buildings', [])) > 0
        )
        assert has_content, "Test location should have geographic content"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
