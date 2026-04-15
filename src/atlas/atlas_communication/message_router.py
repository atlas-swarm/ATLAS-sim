from src.atlas.atlas_communication.communication_bus import CommunicationBus, Message, MessageType

class MessageRouter:
    def __init__(self):
        self.bus = CommunicationBus.get_instance()

    def route_message(self, message: Message):
        self.bus.publish(message)
        self.bus.dispatch()