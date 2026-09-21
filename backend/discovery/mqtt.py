import json, threading
from ..models import Device
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

class MQTTDiscovery:
    def __init__(self, broker, port=1883, username=None, password=None, on_device=None):
        self.broker = broker; self.port = port
        self.username = username; self.password = password
        self.on_device = on_device; self._client = None
    def start(self):
        if not MQTT_AVAILABLE: return
        threading.Thread(target=self._run, daemon=True).start()
    def stop(self):
        if self._client: self._client.disconnect()
    def _run(self):
        c = mqtt.Client()
        if self.username: c.username_pw_set(self.username, self.password)
        def on_connect(c, u, f, rc):
            c.subscribe('homeassistant/+/+/config')
            c.subscribe('homeassistant/+/config')
        def on_message(c, u, msg):
            try:
                p = json.loads(msg.payload.decode())
                dev = Device(name=p.get('name', 'unknown'), device_type='mqtt',
                    address=self.broker, port=self.port, protocol="mqtt",
                    properties={'topic': msg.topic,
                        'unique_id': p.get('unique_id', ''), 'payload': p})
                if self.on_device: self.on_device(dev)
            except Exception as e: print(f"[mqtt] {e}")
        c.on_connect = on_connect; c.on_message = on_message; self._client = c
        try: c.connect(self.broker, self.port, 60); c.loop_forever()
        except Exception as e: print(f"[mqtt] connect error: {e}")

_disc = {}
def start_mqtt_discovery(broker, port=1883, username=None, password=None, on_device=None):
    key = f"{broker}:{port}"
    if key not in _disc:
        d = MQTTDiscovery(broker, port, username, password, on_device)
        d.start()
        _disc[key] = d
    return _disc[key]
