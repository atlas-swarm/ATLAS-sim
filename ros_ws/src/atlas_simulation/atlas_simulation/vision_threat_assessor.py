
if __name__ == "__main__":
    from yolo_detector import Detection
    from aruco_identifier import MarkerMatch

    det = Detection(object_type="person", confidence=0.85, bounding_box=(100, 100, 200, 200))
    zone = [(50, 50), (300, 50), (300, 300), (50, 300)]
    track = {"obj_1": [(150, 150), (155, 155), (160, 160)]}
    markers = []

    result = assess_detection(det, markers, zone, track, "obj_1")
    print(f"object_type   : {result.object_type}")
    print(f"affiliation   : {result.affiliation}")
    print(f"behavior_score: {result.behavior_score}")
    print(f"final_score   : {result.final_threat_score}")
    print(f"threat_level  : {result.threat_level}")
    print(f"reason        : {result.reason}")
