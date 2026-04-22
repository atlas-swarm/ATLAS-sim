from collections import deque
from typing import List

from src.atlas.atlas_communication.communication_bus import CommunicationBus, Message, MessageType
from src.atlas.atlas_threat.threat_alert import ThreatAlert


class AlertDisplay:
    """AlertDisplay: gelen ThreatAlert'leri kuyruğa alır.

    max_queue_size aşıldığında en eski alert alert_history'ye taşınır.
    Can'ın CommandCenter UI'ı hazır olduğunda bu stub yerini alacak.
    """

    def __init__(self, max_queue_size: int = 10):
        self.max_queue_size = max_queue_size
        self.alert_queue: deque = deque()
        self.alert_history: List[ThreatAlert] = []

    def enqueue_alert(self, alert: ThreatAlert):
        if len(self.alert_queue) >= self.max_queue_size:
            oldest = self.alert_queue.popleft()
            self.alert_history.append(oldest)
        self.alert_queue.append(alert)

    def get_active_alerts(self) -> List[ThreatAlert]:
        return list(self.alert_queue)

    def acknowledge_alert(self, alert_id: str) -> bool:
        for alert in self.alert_queue:
            if alert.alert_id == alert_id:
                alert.is_acknowledged = True
                return True
        return False


class CommandCenterInterface:
    """Can'ın CommandCenter sınıfları hazır olana kadar kullanılacak stub.

    CommunicationBus'a subscribe olur ve gelen THREAT_ALERT mesajlarını
    AlertDisplay'e yönlendirir.

    Gerçek implementasyonla değiştirirken:
      - on_alert_received() imzası aynı kalmalı (Message parametresi)
      - alert_display alanı korunabilir veya Can'ın UI sınıfıyla swap edilebilir
    """

    def __init__(self, max_queue_size: int = 10):
        self.alert_display = AlertDisplay(max_queue_size=max_queue_size)
        self._bus = CommunicationBus.get_instance()
        self._bus.subscribe(MessageType.THREAT_ALERT, self.on_alert_received)

    def on_alert_received(self, message: Message):
        alert: ThreatAlert = message.payload
        self.alert_display.enqueue_alert(alert)

    def teardown(self):
        """Test veya reset sırasında subscription'ı temizle."""
        self._bus.unsubscribe(MessageType.THREAT_ALERT, self.on_alert_received)
