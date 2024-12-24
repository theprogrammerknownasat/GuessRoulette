import asyncio

import wifi
import socketpool
import board
import digitalio
import random
import time
import rotaryio
import pwmio
import supervisor
import adafruit_minimqtt.adafruit_minimqtt as MQTT
import json

ID = 1

LIMITED = True

class MQTTGameClient:
    def __init__(self, client_id, leds):
        self.leds = leds
        self.client_id = client_id
        self.mqtt_client = None
        self.connected = False
        self.callback = None
        self.ssid = "GuessRoulette"
        self.password = "password123"
        
        # Turn on status LEDs
        self.leds["led0"].value = True  # WiFi status
        self.leds["led1"].value = True  # MQTT status

        self.last_ping = time.monotonic()
        
        self.connect()

    async def ping_loop(self):
        while True:
            if self.connected:
                self.publish("game/server", json.dumps({
                    "type": "ping",
                    "id": self.client_id
                }))
            await asyncio.sleep(5)  # Ping every 5 seconds
        
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
                self.leds["led0"].value = False
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

    def on_connect(self, client, userdata, flags, rc):
        print(f"Connected with result code {rc}")
        if rc == 0:
            self.connected = True
            self.leds["led1"].value = False
            # Subscribe to topics
            topics = [
                f"game/client/{self.client_id}",
                "game/broadcast",
                "game/roles/#",
                "game/health",
            ]
            for topic in topics:
                client.subscribe(topic)

            connect_payload = {"type": "connect", "id": self.client_id}
            self.publish("game/server", json.dumps(connect_payload))

    def on_disconnect(self, client, userdata, rc):
        print(f"Disconnected with result code {rc}")
        self.connected = False
        self.leds["led1"].value = True
        # Send disconnect message before fully disconnecting
        try:
            self.publish("game/server", json.dumps({
                "type": "disconnect",
                "id": self.client_id
            }))
        except:
            pass  # Ignore errors when trying to send disconnect
            
    def publish(self, topic, message, retain=False):
        if not self.connected:
            self.connect()
        try:
            print(f"Publishing to {topic}: {message}")
            self.mqtt_client.publish(topic, message, retain=False, qos=1)
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



class SevenSegmentDisplay:
    def __init__(self):
        """Initialize display hardware and buffers"""
        # Pin mapping
        self.pins = {
            "ser": board.GP2,
            "rck": board.GP4, 
            "sck": board.GP3,
            "oe1": board.GP5,
            "oe2": board.GP6
        }
        
        # Setup GPIO
        self.display = {
            pin: digitalio.DigitalInOut(gpio) 
            for pin, gpio in self.pins.items()
        }
        
        # Configure outputs
        for pin in self.display.values():
            pin.direction = digitalio.Direction.OUTPUT
            
        # Enable display (active low)
        self.display["oe1"].value = False
        self.display["oe2"].value = False
        
        # Initialize buffers
        self.display_buffer = [0] * 4
        self.decimal_points = [False] * 4

    # Segment patterns for digits 0-9
    @staticmethod
    def get_segment_encoding(digit, decimal=False):
        patterns = [
            0b00111111,  # 0
            0b00000110,  # 1
            0b01011011,  # 2
            0b01001111,  # 3
            0b01100110,  # 4
            0b01101101,  # 5
            0b01111101,  # 6
            0b00000111,  # 7
            0b01111111,  # 8
            0b01101111   # 9
        ]
        return patterns[digit] | (0b10000000 if decimal else 0)
    
    @staticmethod
    def get_letter_encoding(letter):
        patterns = {
            # Uppercase letters
            'A': 0b01110111,
            'C': 0b00111001,
            'E': 0b01111001,
            'F': 0b01110001,
            'H': 0b01110110,
            'I': 0b00000110,
            'J': 0b00011110,
            'L': 0b00111000,
            'O': 0b00111111,
            'P': 0b01110011,
            'S': 0b01101101,
            'U': 0b00111110,
            
            # Lowercase letters
            'b': 0b01111100,
            'c': 0b01011000,
            'd': 0b01011110,
            'h': 0b01110100,
            'i': 0b00000100,
            'n': 0b01010100,
            'o': 0b01011100,
            'r': 0b01010000,
            't': 0b01111000,
            'u': 0b00011100,
            
            # Space/blank
            ' ': 0b00000000
        }
        return patterns.get(letter, 0b10000000)  # Returns DP only if character not found

    def display_text(self, text):
        # Convert text to uppercase and pad with spaces if needed
        text = (text.upper() + "    ")[:4]
        # Update display buffer with letter patterns
        self.display_buffer = [
            self.get_letter_encoding(text[0]),
            self.get_letter_encoding(text[1]),
            self.get_letter_encoding(text[2]),
            self.get_letter_encoding(text[3])
        ]
    
    async def flash_decimals(self):
        """Flash all decimal points"""
        while True:
            # Turn decimals on
            self.decimal_points = [True, True, True, True]
            await asyncio.sleep(0.3)
            # Turn decimals off
            self.decimal_points = [False, False, False, False]
            await asyncio.sleep(0.5)

    def _shift_out(self, value):
        # Shift out 8 bits, MSB first
        for i in range(8):
            bit = (value >> (7 - i)) & 1
            self.display["ser"].value = bit
            self.display["sck"].value = False
            self.display["sck"].value = True

    def display_number(self, number):
        if not (0 <= number <= 9999):
            raise ValueError("Number must be between 0000 and 9999")
        
        # Convert number to digits and update buffer
        self.display_buffer = [
            (number // 1000) % 10,
            (number // 100) % 10,
            (number // 10) % 10,
            number % 10
        ]

    async def refresh_display(self):
        while True:
            # Display each digit
            for position, value in enumerate(self.display_buffer):
                # Shift cathode select (will cascade to second register)
                self._shift_out(1 << position)
                # Shift segment pattern
                self._shift_out(self.get_segment_encoding(value, self.decimal_points[position]))
                # Latch data
                self.display["rck"].value = False
                self.display["rck"].value = True
                
                # Small delay between digits
                await asyncio.sleep(0.002)

    def display_off(self):
        self.display["oe1"].value = True
        self.display["oe2"].value = True

    def display_on(self):
        self.display["oe1"].value = False
        self.display["oe2"].value = False

    def clear(self):
        # Clear by shifting out zeros
        self._shift_out(0x00)
        self._shift_out(0x00)
        self.display["rck"].value = False
        self.display["rck"].value = True
        self.display_buffer = [0, 0, 0, 0]

class PlayerState:
    DEFAULT = 1
    PICKER = 2
    GUESSER = 3
    BETTER = 4
    DEAD = 5

class Controller:
    def __init__(self):
        self.running = True
        # Initialize hardware
        self._setup_hardware()
        # Initialize display
        self.display = SevenSegmentDisplay()
        asyncio.run(self.display_boot())
        
        # Initialize MQTT client
        self.client = MQTTGameClient(ID, self.leds)

        self.client.set_callback(self._on_mqtt_message)
        
        # Game state
        self.display_flash = False
        self.display_health = True
        self.role = PlayerState.DEFAULT
        self.health = 100 if not LIMITED else 15
        self.start = False
        self.role_number = None
        self.guess_ready = False

        self.keywords = {
            "exit": self.close,
            "clear": self.display.clear,
            "win": self.start_win,
            "off": self.display.display_off,
            "reset": supervisor.reload
        }

        self.ping_task = asyncio.create_task(self.client.ping_loop())
    
    def start_win(self):
        asyncio.run(self._start_win())

    def _on_mqtt_message(self, topic, message):
        try:
            # Parse incoming JSON
            payload = json.loads(message)
            # Pass payload to our game logic
            self.process_server_data(payload)
        except Exception as e:
            print(f"JSON parse error: {e}")

    async def display_boot(self):
        self.display.display_on()
        self.display.display_text("PICO")
        for led in self.leds.values():
            led.value = True
            await asyncio.sleep(0.1)
        for led in self.leds.values():
            led.value = False
            await asyncio.sleep(0.1)
        await asyncio.sleep(1.2)
        self.display.display_off()
        self.display.clear()

    def _setup_hardware(self):
        # Setup encoders
        self.encoder0 = rotaryio.IncrementalEncoder(board.GP13, board.GP12)
        self.encoder1 = rotaryio.IncrementalEncoder(board.GP9, board.GP8)
        self.encoder0.position = 0
        self.encoder1.position = 0
        self.encoder0_counter = 0
        self.encoder1_counter = 0

        # Setup buttons
        self.buttons = {
            "encoder0_btn": self._setup_button(board.GP11, True),
            "encoder1_btn": self._setup_button(board.GP7, True),
            "btn0": self._setup_button(board.GP21),
            "btn1": self._setup_button(board.GP20),
            "btn2": self._setup_button(board.GP19),
            "btn3": self._setup_button(board.GP18)
        }

        # Setup LEDs
        self.leds = {
            "led0": self._setup_led(board.GP22),
            "led1": self._setup_led(board.GP26),
            "led2": self._setup_led(board.GP27),
            "led3": self._setup_led(board.GP28)
        }

    async def flash_display(self):
        while self.display_flash:
            flash_task = asyncio.create_task(self.display.flash_decimals())
            while self.display_flash:
                await asyncio.sleep(0.1)
            flash_task.cancel()
            self.display.decimal_points = [False, False, False, False]

    async def main(self):
        """Main game loop"""
        self.display.display_on()
        display_task = asyncio.create_task(self.display.refresh_display())
        flash_task = None
        last_heartbeat = time.monotonic()
        
        try:
            while self.running:
                current_time = time.monotonic()
                if current_time - last_heartbeat >= 5.0:
                    if not self.client.connected:
                        self.client.connect()
                    last_heartbeat = current_time
                # Check MQTT messages
                self.client.check_messages()
                
                # Update display based on state
                if self.display_health:
                    if LIMITED:
                        self._display_binary(self.health)
                    else:
                        self.display.display_number(self.health)


                if self.display_flash and not flash_task:
                    flash_task = asyncio.create_task(self.flash_display())
                elif not self.display_flash and flash_task:
                    flash_task.cancel()
                    flash_task = None
                    self.display.decimal_points = [False] * 4
                
                # Handle input if active role
                if self.role not in [PlayerState.DEFAULT, PlayerState.DEAD] and not self.guess_ready:
                    self.pick()
                
                await asyncio.sleep(0.01)
                
        except Exception as e:
            print(f"Main loop error: {e}")
        finally:
            if flash_task: 
                flash_task.cancel()
            display_task.cancel()
            self.display.display_off()
            self.display.clear()
            self.ping_task.cancel()

    async def _start_win(self):
        self.display_flash = True
        await asyncio.sleep(14)
        self.display_flash = False

    def _setup_led(self, pin):
        """Setup LED pin as output"""
        led = digitalio.DigitalInOut(pin)
        led.direction = digitalio.Direction.OUTPUT
        return led
    
    def close(self):
        self.display.display_off()
        self.running = False
        self.client.disconnect()

    def process_server_data(self, payload):
        msg_type = payload.get('type')
        data = payload.get('data')

        if msg_type == "start":
            self.start = True
            print("Game started")
        elif msg_type == "role":
            self._handle_role(data)
        elif msg_type == "health":
            health_val = payload.get("health", None)
            self._handle_health(health_val)
        elif msg_type in self.keywords:
            self.keywords[msg_type]()

    def _handle_health(self, health_data):
        if health_data is None:
            return
        try:
            health = int(health_data)
            if health <= 0:
                health = 0
                self.role = PlayerState.DEAD
            self.health = health
        except ValueError:
            print("Invalid health value")

    def _handle_role(self, role_data):
        try:
            if "+" in role_data:
                role_type, designation = role_data.split("+")
                if role_type == str(PlayerState.GUESSER):
                    self.role = PlayerState.GUESSER
                    self.role_number = designation
                elif role_type == str(PlayerState.BETTER):
                    self.role = PlayerState.BETTER
                    self.role_number = designation
            else:
                if role_data == str(PlayerState.PICKER):
                    self.role = PlayerState.PICKER
                elif role_data == str(PlayerState.DEAD):
                    self.role = PlayerState.DEAD

            self.guess_ready = False
            self.display_health = False
            self.display.display_number(0)
            print(f"Received role: {self.role}")
        except Exception as e:
            print(f"Error handling role: {e}")

    def _setup_button(self, pin, pullup=False):
        """Setup button with optional pullup"""
        button = digitalio.DigitalInOut(pin)
        button.direction = digitalio.Direction.INPUT
        if pullup:
            button.pull = digitalio.Pull.UP
        return button

    def pick(self):
        """Handle encoder input and button presses for picking numbers"""
        # Get encoder position changes
        encoder_position = self.encoder0.position
        if encoder_position > self.encoder0_counter:
            self.encoder0_counter = min(100, self.encoder0_counter + 1) if not LIMITED else min(15, self.encoder0_counter + 1)
            self.encoder0.position = self.encoder0_counter
        elif encoder_position < self.encoder0_counter:
            self.encoder0_counter = max(0, self.encoder0_counter - 1) if not LIMITED else max(0, self.encoder0_counter - 1)
            self.encoder0.position = self.encoder0_counter
        
        # Update display with current counter value
        if not self.display_health:
            if LIMITED:
                self._display_binary(self.encoder0_counter)
            self.display.display_number(self.encoder0_counter)
        
        # Check for button press to confirm selection
        print(self.buttons["btn3"].value, self.buttons["btn0"].value)
        if self.buttons["btn3"].value or self.buttons["btn0"].value:
            self._send_pick()

    def _send_pick(self):
        self.guess_ready = True
        self.display_flash = False
        self.display_health = True
        
        if self.role == PlayerState.PICKER:
            self.client.publish("game/picker/response", json.dumps({
                "type": "pick",
                "data": self.encoder0_counter,
                "id": ID
            }))
        elif self.role == PlayerState.GUESSER:
            self.client.publish("game/guesser/response", json.dumps({
                "type": "guess",
                "data": self.encoder0_counter,
                "id": ID,
                "index": self.role_number
            }))
        elif self.role == PlayerState.BETTER:
            self.client.publish("game/better/response", json.dumps({
                "type": "bet",
                "data": self.encoder0_counter,
                "id": ID,
                "index": self.role_number
            }))

        self.encoder0_counter = 0
        self.encoder0.position = 0

    def _display_binary(self, number):
        """Display number in binary using LEDs"""
        # Convert number to binary and pad to 4 bits
        binary = f"{number:04b}"
        # Update LEDs
        for i, bit in enumerate(binary):
            self.leds[f"led{i}"].value = (bit == '1')


if __name__ == "__main__":
    controller = Controller()
    asyncio.run(controller.main())
