from __future__ import annotations

from affiliation_scorer import AffiliationClass
from vision_threat_assessor import ThreatAssessment

_UNKNOWN_AFFILIATIONS = {AffiliationClass.UNKNOWN.value, AffiliationClass.UNKNOWN_EXTERNAL.value}
_HIGH_THREAT_LEVELS = {"HIGH", "MEDIUM"}


class SwarmAffilliationHandler:
    def __init__(self) -> None:
        self.confirmed_friendlies: dict[str, ThreatAssessment] = {}
        self.flagged_unknowns: dict[str, ThreatAssessment] = {}

    def process_assessment(self, assessment: ThreatAssessment) -> str:
        if assessment.affiliation == AffiliationClass.FRIENDLY_CONFIRMED.value:
            self.confirmed_friendlies[assessment.object_id] = assessment
            return "FRIENDLY_CONFIRMED"

        if assessment.affiliation == AffiliationClass.FRIENDLY_PROBABLE.value:
            return "MONITOR"

        if (
            assessment.affiliation in _UNKNOWN_AFFILIATIONS
            and assessment.threat_level in _HIGH_THREAT_LEVELS
        ):
            self.flagged_unknowns[assessment.object_id] = assessment
            return "FLAG"

        return "IGNORE"

    def get_confirmed_friendlies(self) -> list[ThreatAssessment]:
        return list(self.confirmed_friendlies.values())

    def get_flagged_unknowns(self) -> list[ThreatAssessment]:
        return list(self.flagged_unknowns.values())

    def clear(self) -> None:
        self.confirmed_friendlies.clear()
        self.flagged_unknowns.clear()


if __name__ == "__main__":
    handler = SwarmAffilliationHandler()

    assessments = [
        ThreatAssessment(
            object_id="obj_0",
            object_type="car",
            affiliation="FRIENDLY_CONFIRMED",
            affiliation_score=1.0,
            behavior_score=0.10,
            final_threat_score=0.00,
            threat_level="NONE",
            reason="affiliation=FRIENDLY_CONFIRMED(modifier=0.00)",
        ),
        ThreatAssessment(
            object_id="obj_1",
            object_type="person",
            affiliation="UNKNOWN_EXTERNAL",
            affiliation_score=0.10,
            behavior_score=0.75,
            final_threat_score=0.75,
            threat_level="HIGH",
            reason="affiliation=UNKNOWN_EXTERNAL(modifier=1.00), in_zone",
        ),
        ThreatAssessment(
            object_id="obj_2",
            object_type="truck",
            affiliation="FRIENDLY_PROBABLE",
            affiliation_score=0.65,
            behavior_score=0.35,
            final_threat_score=0.12,
            threat_level="NONE",
            reason="affiliation=FRIENDLY_PROBABLE(modifier=0.35)",
        ),
    ]

    for a in assessments:
        result = handler.process_assessment(a)
        print(f"{a.object_id} ({a.affiliation}) → {result}")

    print(f"confirmed_friendlies: {[a.object_id for a in handler.get_confirmed_friendlies()]}")
    print(f"flagged_unknowns: {[a.object_id for a in handler.get_flagged_unknowns()]}")
