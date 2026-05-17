from __future__ import annotations

import dataclasses

from atlas_communication.communication_bus import CommunicationBus
from vision_threat_assessor import ThreatAssessment

VISION_THREAT_MSG_TYPE: str = "VISION_THREAT"


class VisionBridge:
    def __init__(self, communication_bus: CommunicationBus) -> None:
        self._bus = communication_bus

    def publish_assessment(self, assessment: ThreatAssessment) -> None:
        self._bus.publish(VISION_THREAT_MSG_TYPE, dataclasses.asdict(assessment))

    def publish_batch(self, assessments: list[ThreatAssessment]) -> None:
        for assessment in assessments:
            if assessment.threat_level != "NONE":
                self.publish_assessment(assessment)


if __name__ == "__main__":
    class _BusStub:
        def __init__(self) -> None:
            self.published: list[tuple[str, dict]] = []

        def publish(self, msg_type: str, payload: dict) -> None:
            self.published.append((msg_type, payload))
            print(f"published: type={msg_type!r}, payload={payload}")

    stub = _BusStub()
    bridge = VisionBridge(stub)  # type: ignore[arg-type]

    dummy = ThreatAssessment(
        object_id="obj_0",
        object_type="person",
        affiliation="UNKNOWN_EXTERNAL",
        affiliation_score=0.10,
        behavior_score=0.75,
        final_threat_score=0.75,
        threat_level="HIGH",
        reason="affiliation=UNKNOWN_EXTERNAL(modifier=1.00), in_zone, mobile_type(person)",
    )

    bridge.publish_batch([dummy])
    print(f"Total published: {len(stub.published)}")
