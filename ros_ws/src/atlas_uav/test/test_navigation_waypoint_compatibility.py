from atlas_common import GeoCoordinate, Waypoint
from atlas_uav.navigation_controller import NavigationController


def test_navigation_controller_accepts_shared_waypoints() -> None:
    controller = NavigationController(uav_id="1")
    waypoint_a = Waypoint(
        coordinate=GeoCoordinate(latitude=39.0, longitude=32.0, altitude=100.0),
        waypoint_id="1",
    )
    waypoint_b = Waypoint(
        coordinate=GeoCoordinate(latitude=39.1, longitude=32.1, altitude=120.0),
        waypoint_id="2",
    )

    controller.load_route([waypoint_b, waypoint_a])

    current = controller.current_waypoint()
    assert current is not None
    assert current.coordinate.latitude == 39.0
    assert controller.has_reached(
        GeoCoordinate(latitude=39.0, longitude=32.0, altitude=0.0)
    )
