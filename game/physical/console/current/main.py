import asyncio
import random
import time
import array
import math

import wifi
import busio
import socketpool
import board
import digitalio
import pulseio
import rotaryio
import pwmio
import adafruit_displayio_sh1106
import displayio
import json 
import adafruit_minimqtt.adafruit_minimqtt as MQTT


class Display:
    def __init__(self):
        displayio.release_displays()
        
        i2c = busio.I2C(scl=board.GP15, sda=board.GP14, frequency=400000)
        display_bus = displayio.I2CDisplay(i2c, device_address=0x3C)
        self.display = adafruit_displayio_sh1106.SH1106(display_bus, width=130, height=64, rotation=180)
        self.current_group = None
        
    async def boot(self):
        # Create bitmap
        bitmap = displayio.Bitmap(130, 64, 2)
        
        byte_index = 0
        with open("/images/boot", "r") as f:
            for line in f:
                # Split line into individual hex strings
                hex_values = line.strip().split(',')
                
                for hex_str in hex_values:
                    # Clean and validate hex string
                    hex_str = hex_str.strip().strip("'").strip('"')
                    if hex_str and hex_str != '0x':
                        try:
                            # Convert hex string to int, handling '0x' prefix
                            byte = int(hex_str.replace('0x', ''), 16)
                            
                            # Calculate position
                            x = (byte_index * 8) % 128
                            y = (byte_index * 8) // 128
                            
                            # Set 8 bits
                            for bit in range(8):
                                if x + bit < 128:  # Boundary check
                                    bitmap[x + bit, y] = (byte >> (7 - bit)) & 1
                            
                            byte_index += 1
                            
                            # Give system time occasionally
                            if byte_index % 16 == 0:
                                time.sleep(0.001)
                                
                        except ValueError as e:
                            print(f"Invalid hex value: {hex_str}")
                            continue
        
        palette = displayio.Palette(2)
        palette[0] = 0x000000
        palette[1] = 0xFFFFFF
        
        tile_grid = displayio.TileGrid(bitmap, pixel_shader=palette)
        group = displayio.Group()
        group.append(tile_grid)
        self.current_group = group
        self.display.root_group = group

    def show_test_pattern(self):
        """Show test pattern if image fails"""
        bitmap = displayio.Bitmap(128, 64, 1)
        palette = displayio.Palette(1)
        palette[0] = 0xFFFFFF
        
        for x in range(128):
            for y in range(64):
                bitmap[x, y] = (x + y) % 2
                
        tile_grid = displayio.TileGrid(bitmap, pixel_shader=palette)
        group = displayio.Group()
        group.append(tile_grid)
        self.display.root_group = group
        
    def update_status(self, text):
        #self.status.text = text
        pass
        
    def clear(self):
        """Clear display"""
        group = displayio.Group()
        self.current_group = group
        self.display.root_group = group

class MQTTGameClient:
    def __init__(self, client_id):
        self.client_id = client_id
        self.mqtt_client = None
        self.connected = False
        self.callback = None
        self.ssid = "GuessRoulette"
        self.password = "password123"

        self.last_ping = time.monotonic()
        
        self.connect()
        
    def connect(self):
        while True:
            try:
                print("\nConnecting to WiFi...")
                wifi.radio.stop_station()
                wifi.radio.stop_ap()
                time.sleep(2)

                wifi.radio.connect(self.ssid, self.password)
                while not wifi.radio.connected:
                    print("Waiting for connection...")
                    time.sleep(1)

                print("Connected to WiFi!")
                print("IP Address:", str(wifi.radio.ipv4_address))
                time.sleep(5)  # WiFi stabilizationa
                pool = socketpool.SocketPool(wifi.radio)
                print("Connecting to MQTT broker...")

                # Setup MQTT client
                self.mqtt_client = MQTT.MQTT(
                    broker="192.168.137.1",
                    port=1883,
                    client_id=f"pico_{self.client_id}",
                    socket_pool=pool,
                    socket_timeout=0.5,    # Socket timeout shortest
                    keep_alive=15,         # Keep alive longest
                )

                self.mqtt_client.on_connect = self.on_connect
                self.mqtt_client.on_disconnect = self.on_disconnect
                self.mqtt_client.on_message = self.on_message

                self.mqtt_client.connect()
                print("Connected to MQTT broker")
                return
            except Exception as e:
                print(f"Connection failed: {e}")

    async def ping_loop(self):
        while True:
            if self.connected:
                self.publish("game/server", json.dumps({
                    "type": "ping",
                    "id": self.client_id
                }))
            await asyncio.sleep(5)  # Ping every 5 seconds

    def on_connect(self, client, userdata, flags, rc):
        print(f"Connected with result code {rc}")
        if rc == 0:
            self.connected = True
            # Subscribe to topics
            topics = [
                f"game/client/{self.client_id}",
                "game/broadcast"
            ]
            for topic in topics:
                client.subscribe(topic)

            connect_payload = {"type": "connect", "id": self.client_id}
            self.publish("game/server", json.dumps(connect_payload))

    def on_disconnect(self, client, userdata, rc):
        print(f"Disconnected with result code {rc}")
        self.connected = False
        self.leds["led1"].value = True
        # Try to reconnect
        self.connect()
            
    def publish(self, topic, message):
        if not self.connected:
            self.connect()
        try:
            print(f"Publishing to {topic}: {message}")
            self.mqtt_client.publish(topic, message, qos=1)
            return True
        except Exception as e:
            print(f"Publish failed: {e}")
            return False
            
    def on_message(self, client, topic, message):
        print(f"Received message on {topic}: {message}")
        try:
            if self.callback:
                self.callback(topic, message)
        except Exception as e:
            print(f"Message handling error: {e}")
            
    def set_callback(self, callback):
        self.callback = callback
        
    def check_messages(self):
        self.mqtt_client.loop(1.0)

class Console:
    def __init__(self):
        self.display = Display()

        self.lights = {
            2: digitalio.DigitalInOut(board.GP0),
            3: digitalio.DigitalInOut(board.GP1),
            4: digitalio.DigitalInOut(board.GP2),
            5: digitalio.DigitalInOut(board.GP3),
            6: digitalio.DigitalInOut(board.GP5),
            7: digitalio.DigitalInOut(board.GP4),
            8: digitalio.DigitalInOut(board.GP6),
            9: digitalio.DigitalInOut(board.GP7),
            10: digitalio.DigitalInOut(board.GP8),
            1: digitalio.DigitalInOut(board.GP9)
        }

        for light in self.lights.values():
            light.direction = digitalio.Direction.OUTPUT
            light.value = True
            time.sleep(0.1)
        for light in self.lights.values():
            light.value = False
            time.sleep(0.1)

        self.start = digitalio.DigitalInOut(board.GP10)
        self.start.direction = digitalio.Direction.INPUT

        self.running = True

        self.clients = []
        self.choices = []

        self.started = False

        asyncio.run(self.startup())

    def light_wheel(self, choice=None, double_choice=False):
        def spin_to_choice(target, initial_speed=0.02, skip_light=None):
            speed = initial_speed
            spins = 2  # Fixed number for consistent timing
            do_fake = random.random() < 0.25 and not skip_light  # Only fake on first spin
            
            for spin in range(spins):
                for light_id, light in self.lights.items():
                    if light_id == skip_light:
                        continue
                        
                    light.value = True
                    time.sleep(speed)
                    light.value = False
                    
                    if spin == spins - 1 and light_id == target - 1 and do_fake:
                        light.value = True
                        time.sleep(0.3)  # Brief fake pause
                        light.value = False
                        continue
                        
                    if spin == spins - 1 and light_id == target:
                        light.value = True
                        return
                        
                speed *= 2.2  # Faster exponential slowdown

        self.turn_off_all_lights()
        if not choice:
            raise ValueError("No choice provided")

        if double_choice:
            if not isinstance(choice, list) or len(choice) != 2:
                raise ValueError("Choice must be a list of two values")
                
            # First spin leaving light on
            spin_to_choice(choice[0], initial_speed=0.02)
            time.sleep(0.3)  # Quick pause between spins
            
            # Second spin skipping lit light
            spin_to_choice(choice[1], initial_speed=0.02, skip_light=choice[0])
        else:
            spin_to_choice(choice, initial_speed=0.02)

    async def startup(self):
        """Handle startup sequence"""
        # Show boot screen
        await self.display.boot()
        
        # Initialize WiFi
        self.client = MQTTGameClient(0)

        self.client.set_callback(self._on_mqtt_message)
        
        # Once connected, clear screen
        if self.client.connected:
            self.display.clear()


    def turn_off_all_lights(self):
        for light in self.lights.values():
            light.value = False

    def _on_mqtt_message(self, topic, message):
        try:
            # Parse incoming JSON
            payload = json.loads(message)
            # Pass payload to our game logic
            self.process_server_data(payload)
        except Exception as e:
            print(f"JSON parse error: {e}")

    async def main(self):
        last_heartbeat = time.monotonic()
        while self.running:
            current_time = time.monotonic()
            if current_time - last_heartbeat >= 5.0:
                if not self.client.connected:
                    self.client.connect()
                last_heartbeat = current_time
            # Check MQTT messages
            self.client.check_messages()
    

            if not self.started:
                for client in self.clients:
                    if client == 0:
                        pass
                    else:
                        if int(client) in self.lights.keys():
                            self.lights[client].value = True
                        else:
                            self.lights[client].value = False
            else:
                self.turn_off_all_lights()


            if self.start.value:
                self.turn_off_all_lights()
                self.started = True
                self.client.publish("game/console", json.dumps({"type": "start"}))

            await asyncio.sleep(0.1)
            
    def process_server_data(self, payload):
        msg_type = payload.get('type')
        data = payload.get('data')

        if msg_type == "clients":
            try:
                # Clean up dict_keys format and extract numbers
                cleaned = data.replace('dict_keys(', '').replace(')', '').replace('[', '').replace(']', '')
                client_list = cleaned.replace(' ', '').split(',')
                self.clients = [int(x) for x in client_list if x.isdigit()]
            except Exception as e:
                print(f"Error parsing clients: {e}")
                self.clients = []
        elif msg_type == "light_wheel":
            if "off" in data:
                self.turn_off_all_lights()
            else:
                self.light_wheel(int(data)) if not isinstance(data, list) else self.light_wheel(data, double_choice=True)
            self.client.publish("game/wheel/response", 
                json.dumps({"type": "light_wheel", "data": "done"}))
        elif msg_type == "display":
            pass
        elif msg_type == "win":
            pass
        else:
            pass

    def win(self):
        times = 15
        for _ in range(times/2):
            for light in self.lights.values():
                light.value = True
            
            time.sleep(0.5)
            self.turn_off_all_lights()

if __name__ == "__main__":
    console = Console()
    asyncio.run(console.main())
    
