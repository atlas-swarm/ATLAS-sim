"""
Entegrasyon testi: ThreatDetector → CommunicationBus → CommandCenterInterface → AlertDisplay

Zincir:
  ThreatDetector.update()
    → CommunicationBus.publish(THREAT_ALERT)
    → CommunicationBus.dispatch()
    → CommandCenterInterface.on_alert_received()
    → AlertDisplay.enqueue_alert()
    → AlertDisplay.get_active_alerts()

Çalıştırma (ros_ws/src dizininden):
  python test_integration.py
"""

import sys
import types
from pathlib import Path

# ROS paket dizinlerini Python path'e ekle
_src = Path(__file__).parent
sys.path.insert(0, str(_src))
sys.path.insert(0, str(_src / "atlas_commandcenter"))  # atlas_commandcenter/atlas_commandcenter/


# atlas_data ve atlas_common henüz mevcut değil — mock olarak tanımla
def _make_mock_module(name):
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


# atlas_data henüz mevcut değil — mock olarak tanımla
atlas_data_mod = _make_mock_module("atlas_data")
atlas_data_mod.MissionPlan = None
atlas_data_mod.DataLogger = None

# Şimdi gerçek modüller import edilebilir
from atlas_communication.communication_bus import CommunicationBus, MessageType  # noqa: E402
from atlas_communication.telemetry_packet import GeoCoordinate                   # noqa: E402
from atlas_threat.threat_detector import ThreatDetector                          # noqa: E402
from atlas_commandcenter.alert_display import AlertDisplay                       # noqa: E402
from atlas_commandcenter.command_center_interface import CommandCenterInterface  # noqa: E402


def setup():
    """Singleton'ları sıfırla, temiz bir ortam hazırla."""
    CommunicationBus._instance = None
    CommandCenterInterface._instance = None


def test_single_uav_alert():
    """UAV-1'in bir tehdit üretip CommandCenter'a ilettiğini doğrula."""
    setup()

    # CommandCenter bağlan (THREAT_ALERT subscribe)
    cc = CommandCenterInterface.get_instance()
    bus = CommunicationBus.get_instance()
    bus.subscribe(MessageType.THREAT_ALERT, cc.on_alert_received)

    # UAV-1: bir tehdit objesinin yanında
    detector = ThreatDetector(uav_id=1)
    uav_position = GeoCoordinate(lat=41.0, lon=29.0, alt=100.0)
    sim_objects = [
        {"type": "VEHICLE", "lat": 41.0, "lon": 29.0},
    ]

    detector.update(uav_position, sim_objects)

    active = cc.alert_display.get_active_alerts()
    assert len(active) == 1, f"Beklenen 1 alert, gelen: {len(active)}"
    assert active[0].classification.value == "VEHICLE"
    assert active[0].uav_id == 1
    assert active[0].is_acknowledged is False
    print("[PASS] test_single_uav_alert")


def test_two_uavs_simultaneous_alerts():
    """2 farklı UAV aynı anda alert ürettiğinde her ikisi de aktif listede olmalı."""
    setup()

    cc = CommandCenterInterface.get_instance()
    bus = CommunicationBus.get_instance()
    bus.subscribe(MessageType.THREAT_ALERT, cc.on_alert_received)

    # UAV-1
    detector_1 = ThreatDetector(uav_id=1)
    pos_1 = GeoCoordinate(lat=41.0, lon=29.0, alt=80.0)
    objects_1 = [{"type": "VEHICLE", "lat": 41.0, "lon": 29.0}]

    # UAV-2
    detector_2 = ThreatDetector(uav_id=2)
    pos_2 = GeoCoordinate(lat=41.5, lon=29.5, alt=120.0)
    objects_2 = [{"type": "PERSON", "lat": 41.5, "lon": 29.5}]

    # Her iki UAV güncelleme yapıyor (dispatch ayrı ayrı tetikleniyor)
    detector_1.update(pos_1, objects_1)
    detector_2.update(pos_2, objects_2)

    active = cc.alert_display.get_active_alerts()
    assert len(active) == 2, f"Beklenen 2 alert, gelen: {len(active)}"

    uav_ids = {a.uav_id for a in active}
    assert uav_ids == {1, 2}, f"UAV id seti yanlis: {uav_ids}"

    classifications = {a.classification.value for a in active}
    assert classifications == {"VEHICLE", "SUSPICIOUS_MOVEMENT"}, (
        f"Classification seti yanlis: {classifications}"
    )

    print("[PASS] test_two_uavs_simultaneous_alerts")


def test_alert_not_delivered_when_out_of_range():
    """Tespit yarıçapı dışındaki objeler alert üretmemeli."""
    setup()

    cc = CommandCenterInterface.get_instance()
    bus = CommunicationBus.get_instance()
    bus.subscribe(MessageType.THREAT_ALERT, cc.on_alert_received)

    detector = ThreatDetector(uav_id=3)
    uav_position = GeoCoordinate(lat=41.0, lon=29.0, alt=100.0)
    # ~1.5 km uzakta → detection_radius=100m dışında
    sim_objects = [{"type": "VEHICLE", "lat": 41.015, "lon": 29.015}]

    detector.update(uav_position, sim_objects)

    active = cc.alert_display.get_active_alerts()
    assert len(active) == 0, f"Beklenen 0 alert, gelen: {len(active)}"
    print("[PASS] test_alert_not_delivered_when_out_of_range")


if __name__ == "__main__":
    test_single_uav_alert()
    test_two_uavs_simultaneous_alerts()
    test_alert_not_delivered_when_out_of_range()
    print("\nTum testler gecti.")
