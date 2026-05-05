"""Basic motion update and geofence enforcement logic."""

from __future__ import annotations

from atlas_simulation.environment_model import EnvironmentModel
from atlas_simulation.models import (
    SimEvent,
    UAVState,
    Vector3D,
    advance_coordinate,
    is_coordinate_inside_boundary,
)


class PhysicsProcessor:
    """Advance UAV positions with a simple linear motion model."""

    def update_positions(
        self,
        uav_states: dict[int, UAVState],
        delta_time_s: float,
        environment: EnvironmentModel,
    ) -> list[SimEvent]:
        """Update all states and return any generated events."""
        generated_events: list[SimEvent] = []

        if delta_time_s < 0:
            raise ValueError("delta_time_s must be non-negative")

        for state in uav_states.values():
            state.position = advance_coordinate(
                state.position,
                state.velocity,
                delta_time_s,
            )
            violation_event = self.apply_boundary_constraints(state, environment)
            if violation_event is not None:
                generated_events.append(violation_event)

        return generated_events

    def apply_boundary_constraints(
        self,
        state: UAVState,
        environment: EnvironmentModel,
    ) -> SimEvent | None:
        """Clamp out-of-bounds UAVs back to their last valid position."""
        if is_coordinate_inside_boundary(
            state.position,
            environment.patrol_boundary,
        ):
            state.last_valid_position = state.position.copy()
            return None

        attempted_position = state.position.copy()
        state.position = state.last_valid_position.copy()
        state.velocity = Vector3D(0.0, 0.0, state.velocity.z)

        return SimEvent(
            event_type="GEOFENCE_VIOLATION",
            uav_id=state.uav_id,
            details={
                "attempted_position": {
                    "latitude": attempted_position.latitude,
                    "longitude": attempted_position.longitude,
                    "altitude": attempted_position.altitude,
                },
                "restored_position": {
                    "latitude": state.position.latitude,
                    "longitude": state.position.longitude,
                    "altitude": state.position.altitude,
                },
            },
        )
