import random
import time


class NetworkSimulator:
    """Ağ koşullarını simüle eder: latency ve packet loss.

    CommunicationBus.dispatch() tarafından her mesaj gönderiminde kullanılır.
    Paket kaybında mesaj sessizce düşürülür — sistem exception fırlatmaz.
    """

    def __init__(self):
        self.latency_ms: int = 0
        self.packet_loss_rate: float = 0.0  # 0.0 = kayıp yok, 1.0 = tüm paketler düşer

    def simulate_latency(self, ms: int):
        """Ağ gecikmesini ayarla (milisaniye)."""
        self.latency_ms = max(0, ms)

    def simulate_packet_loss(self, rate: float):
        """Paket kayıp oranını ayarla. 0.0–1.0 aralığında clamp edilir."""
        self.packet_loss_rate = max(0.0, min(1.0, rate))

    def apply_latency(self):
        """Ayarlanmış latency kadar bekle. dispatch() tarafından çağrılır."""
        if self.latency_ms > 0:
            time.sleep(self.latency_ms / 1000.0)

    def should_drop_packet(self) -> bool:
        """Mevcut packet_loss_rate'e göre bu paketin düşürülmesi gerekip gerekmediğini döndür."""
        if self.packet_loss_rate <= 0.0:
            return False
        return random.random() < self.packet_loss_rate
