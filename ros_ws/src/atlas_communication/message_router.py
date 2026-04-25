from atlas_communication.communication_bus import CommunicationBus, Message, MessageType
# yönlendirici
class MessageRouter:
    def __init__(self):
        self.bus = CommunicationBus.get_instance()

    def route_message(self, message: Message):
        self.bus.publish(message.msg_type, message.payload)
        self.bus.dispatch()