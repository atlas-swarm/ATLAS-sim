from collections import deque
from typing import Dict, List

from atlas_common import MessageType
from atlas_communication.network_simulator import NetworkSimulator

# Bütün subsystemler birbirine bağlı olmadıkları için iletişimleri bu bus üstünden yapıyorlar.
# Sonra ilgili dinleyiciye mesajı iletiyor.


class Message:
    def __init__(self, msg_type: MessageType, payload):
        self.msg_type = msg_type
        self.payload = payload


class CommunicationBus:
    _instance = None

    def __init__(self):
        self.subscribers: Dict[MessageType, List] = {t: [] for t in MessageType}
        self.message_queue: deque = deque()
        self.network_simulator: NetworkSimulator = NetworkSimulator()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = CommunicationBus()
        return cls._instance

    def subscribe(self, msg_type: MessageType, listener):
        if listener not in self.subscribers[msg_type]:
            self.subscribers[msg_type].append(listener)

    def unsubscribe(self, msg_type: MessageType, listener):
        if listener in self.subscribers[msg_type]:
            self.subscribers[msg_type].remove(listener)

    def publish(self, msg_type: MessageType, payload):
        self.message_queue.append(Message(msg_type, payload))

    def dispatch(self):
        while self.message_queue:
            message = self.message_queue.popleft()
            if self.network_simulator.should_drop_packet():
                # Graceful degradation: paket sessizce düşürülür, exception yok
                continue
            self.network_simulator.apply_latency()
            for listener in self.subscribers[message.msg_type]:
                listener(message.payload)
