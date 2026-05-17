
if __name__ == "__main__":
    from yolo_detector import Detection
    from aruco_identifier import MarkerMatch

    det = Detection(object_type="person", confidence=0.85, bounding_box=(100, 100, 200, 200))
    markers_inside = [MarkerMatch(marker_id=10, center=(150, 150), asset_name="atlas_ugv_1")]
    markers_outside = [MarkerMatch(marker_id=20, center=(300, 300), asset_name="command_vehicle")]
    no_markers = []

    cls, score = calculate_affiliation_score(det, markers_inside)
    print(f"Marker inside, type mismatch → {cls.name}, score={score}")

    det2 = Detection(object_type="atlas_ugv_1", confidence=0.9, bounding_box=(100, 100, 200, 200))
    cls2, score2 = calculate_affiliation_score(det2, markers_inside)
    print(f"Marker inside, type match    → {cls2.name}, score={score2}")

    cls3, score3 = calculate_affiliation_score(det, markers_outside)
    print(f"Marker nearby                → {cls3.name}, score={score3}")

    cls4, score4 = calculate_affiliation_score(det, no_markers)
    print(f"No markers                   → {cls4.name}, score={score4}")
