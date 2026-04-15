class NetworkSimulator:
    def __init__(self):
        self.latency_ms: int = 0
        self.packet_loss_rate: float = 0.0

    def simulate_latency(self, ms: int):
        # Hafta 2'de doldurulacak
        self.latency_ms = ms

    def simulate_packet_loss(self, rate: float):
        # Hafta 2'de doldurulacak
        self.packet_loss_rate = rate