import asyncio

import wifi
import socketpool
import board
import digitalio
import random
import time
import rotaryio
import pwmio


class WiFiClient:
    def __init__(self, ssid, password, client_id):
        self.ssid = ssid
        self.password = password
        self.client_id = client_id
        self.sock = None
        self.connected = False
        

        self.identification = None
        self.iden_pin = digitalio.DigitalInOut(board.GP14)
        self.iden_pin.direction = digitalio.Direction.OUTPUT
        self.iden_pin.value = False

        self.clear_iden_pin = digitalio.DigitalInOut(board.GP15)
        self.clear_iden_pin.direction = digitalio.Direction.INPUT

        self._connect()

    def _connect(self):
        attempt = 0
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
                time.sleep(5)  # WiFi stabilization

                print("\nConnecting to server...")
                pool = socketpool.SocketPool(wifi.radio)

                for attempt_num in range(3):
                    try:
                        print(f"Connection attempt {attempt_num + 1}...")
                        self.sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)

                        # Ensure the socket is in blocking mode
                        self.sock.setblocking(True)

                        print("Initiating connection...")
                        self.sock.connect(("192.168.1.180", 8080)) #192.168.4.1

                        print("Sending ID...")
                        id_msg = f"id:{self.client_id}".encode()
                        self.sock.send(id_msg)

                        print("Waiting for response...")
                        self.sock.settimeout(5)

                        buffer = bytearray(1024)
                        bytes_read = self.sock.recv_into(buffer)
                        if bytes_read:
                            response = buffer[:bytes_read].decode()
                            if response == "ok":
                                print("Connected to server!")
                                self.sock.settimeout(None)  # Remove timeout
                                self.connected = True

                                self._handle_identification()
                                return
                            else:
                                print(f"Unexpected response: {response}")
                        else:
                            print("No response received")

                        self.sock.close()
                        self.sock = None
                        time.sleep(2)

                    except Exception as e:
                        print(f"Attempt {attempt_num + 1} failed: {e}")
                        if self.sock:
                            try:
                                self.sock.close()
                            except:
                                pass
                            self.sock = None
                        time.sleep(2)

                raise RuntimeError("All connection attempts failed")

            except Exception as e:
                print(f"Connection failed: {e}")
                if self.sock:
                    try:
                        self.sock.close()
                    except:
                        pass
                self.sock = None
                self.connected = False

                attempt += 1
                wait_time = min(attempt * 2, 10)
                print(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)

    def _handle_identification(self):
        """Handle the identification process with the server"""
        try:
            print("Starting identification process...")
            
            # Initialize identification pins
            self.iden_pin.value = False
            buffer = bytearray(1024)
            
            # Wait for "iden" command
            bytes_read = self.sock.recv_into(buffer)
            if bytes_read:
                response = buffer[:bytes_read].decode()
                if response.strip() == "iden":
                    print("Identification query received")
                    # Set identification pin high
                    self.iden_pin.value = True
                    
                    # Send acknowledgment
                    print("Sending acknowledgment")
                    self.sock.send(b"ok")
                    
                    # Wait for pin assignment
                    buffer = bytearray(1024)
                    bytes_read = self.sock.recv_into(buffer)
                    if bytes_read:
                        response = buffer[:bytes_read].decode()
                        if response.startswith("iden:"):
                            self.identification = response.split(":")[1]
                            print(f"Identification received: {self.identification}")
                                    
                            return True
                        
            return False
            
        except Exception as e:
            print(f"Identification error: {e}")
            self.connected = False
            return False
        
    def send(self, data):
        """Send data to server and wait for 'ok' response."""
        print(f"Sending to server: {data}")
        try:
            if not self.connected:
                self._connect()

            # Ensure blocking mode for send/receive sequence
            self.sock.setblocking(True)

            # Send the data
            self.sock.send(data.encode())

            # Wait for acknowledgment
            buffer = bytearray(1024)
            bytes_read = self.sock.recv_into(buffer)
            if bytes_read:
                response = buffer[:bytes_read].decode()
                if response.strip() == "ok":
                    print("Server acknowledged")
                    return True
                else:
                    print(f"Unexpected server response: {response}")
                    return False
            else:
                print("No response from server")
                return False

        except Exception as e:
            print(f"Send failed: {e}")
            self.connected = False
            self._connect()
            return False

    def receive_from_server(self):
        """Receive data from server and send back 'ok'."""
        try:
            if not self.connected:
                self._connect()
            self.sock.setblocking(False)

            buffer = bytearray(1024)
            bytes_read = self.sock.recv_into(buffer)
            if bytes_read:
                data = buffer[:bytes_read].decode()
                print(f"Received from server: {data}")

                # Send back 'ok'
                self.sock.setblocking(True)
                self.sock.send(b"ok")
                self.sock.setblocking(False)

                return data
        except OSError:
            pass  # No data received
        except Exception as e:
            print(f"Receive failed: {e}")
            self.connected = False
            self._connect()
        finally:
            self.sock.setblocking(True)
        return None

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        wifi.radio.stop_station()


class SevenSegmentDisplay:
    def __init__(self):
        # Initialize pins
        self.display = {
            "ser": digitalio.DigitalInOut(board.GP2),
            "rck": digitalio.DigitalInOut(board.GP4),
            "sck": digitalio.DigitalInOut(board.GP3),
            "oe1": digitalio.DigitalInOut(board.GP5),
            "oe2": digitalio.DigitalInOut(board.GP6),
        }

        # Configure pins as outputs
        for pin in self.display.values():
            pin.direction = digitalio.Direction.OUTPUT

        # Enable outputs (active low)
        self.display["oe1"].value = False
        self.display["oe2"].value = False

        # Initialize display buffer
        self.display_buffer = [0, 0, 0, 0]
        self.decimal_points = [False, False, False, False]

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
        self.client = WiFiClient("Fios-2vFHS", "beam873tow87mice", 1)
        self.running = True

        self.encoder0 = rotaryio.IncrementalEncoder(board.GP12, board.GP13)
        self.encoder0_btn = digitalio.DigitalInOut(board.GP11)
        self.encoder0_counter = 0

        self.encoder0_btn.direction = digitalio.Direction.INPUT
        self.encoder0_btn.pull = digitalio.Pull.UP

        self.encoder1 = rotaryio.IncrementalEncoder(board.GP8, board.GP9)
        self.encoder1_btn = digitalio.DigitalInOut(board.GP7)
        self.encoder1_counter = 0

        self.buttons = {
            "encoder0_btn": self.encoder0_btn,
            "encoder1_btn": self.encoder1_btn,
            "btn0": digitalio.DigitalInOut(board.GP21),
            "btn1": digitalio.DigitalInOut(board.GP20),
            "btn2": digitalio.DigitalInOut(board.GP19),
            "btn3": digitalio.DigitalInOut(board.GP18),
        }

        self.leds = {
            "internal": digitalio.DigitalInOut(board.LED),
            "led0": digitalio.DigitalInOut(board.GP22),
            "led1": digitalio.DigitalInOut(board.GP26),
            "led2": digitalio.DigitalInOut(board.GP27),
            "led3": digitalio.DigitalInOut(board.GP28),
        }

        # backup communication (unused)
        """self.comm = {
            "sda": digitalio.DigitalInOut(board.GP14),
            "scl": digitalio.DigitalInOut(board.GP15)
        }"""

        for led in self.leds.values():
            led.direction = digitalio.Direction.OUTPUT

        self.buttons["btn3"].direction = digitalio.Direction.INPUT

        self.display = SevenSegmentDisplay()

        self.display_flash = False
        self.display_health = True
        self.role = PlayerState.DEFAULT
        self.health = 100
        self.start = False
        self.role_number = None
        self.guess_ready = False

        self.keywords = {
            "exit": self.close(),
            "clear": self.clear(),
            "win": lambda: asyncio.run(self.win())
        }

    def exit(self):
        self.running = False
        self.client.close()
        self.display.clear()
        self.display.display_off()

    async def main(self):
        self.display.display_on()

        display_task = asyncio.create_task(self.display.refresh_display())
        self._flash_task = None
        last_heartbeat = time.monotonic()

        while self.running:
            current_time = time.monotonic()
            if current_time - last_heartbeat >= 1.0:
                try:
                    if self.client.connected:
                        self.client.sock.send(b"heartbeat")
                    last_heartbeat = current_time
                except Exception as e:
                    print(f"Heartbeat failed: {e}")
                    self.display.display_off()
                    self.client.connected = False
                    self.client._connect()
                    self.display.display_on()

            if self.client.clear_iden_pin.value:
                self.client.clear_iden_pin.value = False

            try:
                data = self.client.receive_from_server()

                if data:
                    self.process_server_data(data)

                if self.role == PlayerState.DEAD:
                    self.display.display_off()
                    self.display_health = False
                    self.display_flash = False

                if self.display_health:
                    self.display.display_number(self.health)

                if self.display_flash and not self._flash_task:
                    self._flash_task = asyncio.create_task(self.flash_display())
                elif not self.display_flash and self._flash_task:
                    self._flash_task.cancel()
                    self._flash_task = None
                

                if (self.role is not None) and (self.role is not PlayerState.DEFAULT) and (
                        self.role is not PlayerState.DEAD):
                    if not self.guess_ready:
                        self.display_flash = True
                        self.pick()
                
                await asyncio.sleep(0.001)

            except KeyboardInterrupt:
                self.running = False

    async def flash_display(self):
        while self.display_flash:
            flash_task = asyncio.create_task(self.display.flash_decimals())
            while self.display_flash:
                await asyncio.sleep(0.1)
            flash_task.cancel()
            self.display.decimal_points = [False, False, False, False]


    def clear(self):
        self.display_health = True
        self.display_flash = False
        self.role = PlayerState.DEFAULT if self.role != PlayerState.DEAD else PlayerState.DEAD
        self.start = False
        self.role_number = None
        self.guess_ready = False

    def pick(self):
        current_position = self.encoder0.position
        if current_position != self.encoder0_counter:
            self.encoder0_counter = current_position
            if self.encoder0_counter < 0:
                self.encoder0_counter = 0
                self.encoder0.position = 0
            elif self.encoder0_counter > 100:
                self.encoder0_counter = 100
                self.encoder0.position = 100
            self.display.display_number(self.encoder0_counter)

        if self.buttons["btn3"].value:
            self.guess_ready = True
            self.display_flash = False
            self.display_health = True
            if self.role == PlayerState.PICKER:
                self.client.send(f"pick:{self.encoder0_counter}")
            elif self.role == PlayerState.GUESSER:
                self.client.send(f"guess+{self.role_number}:{self.encoder0_counter}")
            elif self.role == PlayerState.BETTER:
                self.client.send(f"bet+{self.role_number}:{self.encoder0_counter}")

            self.encoder0_counter = 0
            self.encoder0.position = 0
            

    async def win(self):
        # Flash LEDs for 14 seconds
        for _ in range(14):
            for led in self.leds.values():
                led.value = True
            await asyncio.sleep(0.5)
            for led in self.leds.values():
                led.value = False
            await asyncio.sleep(0.5)

    def process_server_data(self, data):
        if data.startswith("start"):
            self.start = True
            print("Game started")
        else:
            if not self.start:
                print(f"Game not started, skipping data: {data}")
            else:
                if data.startswith("role:"):
                    try:
                        role_number = None
                        role_designation = None
                        role = data.split(":")[1]
                        print(f"Role data: {role}")
                        if "+" in role:
                            role_number = role.split("+")[0]
                            role_designation = role.split("+")[1]

                            if "3" in role_number:
                                self.role = PlayerState.GUESSER
                                self.role_number = role_designation
                            elif "4" in role_number:
                                self.role = PlayerState.BETTER
                                self.role_number = role_designation
                        else:
                            if "2" in role:
                                self.role = PlayerState.PICKER
                            elif "5" in role:
                                self.role = PlayerState.DEAD
                            else:
                                print(f"Invalid role number: {role}")


                        self.guess_ready = False
                        self.display_health = False
                        self.display.display_number(0)
                        print(f"Received role: {self.role}")
                        return
                    except ValueError:
                        print("Invalid role number format")
                elif data.startswith("health:"):
                    if (self.role is not None) or (self.role is not PlayerState.DEFAULT):
                        try:
                            health = int(data.split(":")[1])
                            if health <= 0:
                                health = 0
                                self.role = PlayerState.DEAD
                            self.health = health
                            print(f"Received health: {health}")
                        except ValueError:
                            print("Invalid health format")
                    else:
                        print(f"Role not assigned, skipping data: {data}")
                        self.role = data
                # check if data starts with any of the keywords
                elif any(data.startswith(keyword) for keyword in self.keywords):
                    self.keywords[data]()
                else:
                    print(f"Unknown data: {data}")


if __name__ == "__main__":
    controller = Controller()
    asyncio.run(controller.main())
