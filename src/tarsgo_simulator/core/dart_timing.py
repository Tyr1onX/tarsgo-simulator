"""Shared Rules Lab timing assumptions for the RMUC Dart presentation."""

# RMUC 2026 V1.4.0 defines firing and detector windows but does not define
# projectile flight speed or duration. Rules and Pygame use this one-second
# deterministic approximation as the same launch-to-impact timeline.
RULES_LAB_DART_FLIGHT_SECONDS = 1.0
