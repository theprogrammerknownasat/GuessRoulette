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

class WiFiClient:
    def __init__(self, ssid, password, client_id):
        self.ssid = ssid
        self.password = password
        self.client_id = client_id
        self.sock = None
        self.connected = False

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
                        connected = False
                        # try to connect to 192.168.137.1, and if that doesnt work, go to 169.254.104.12
                        self.sock.connect(("192.168.137.1", 8080))


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

class Console:
    def __init__(self):
        self.display = Display()

        self.lights = {
            1: digitalio.DigitalInOut(board.GP0),
            2: digitalio.DigitalInOut(board.GP1),
            3: digitalio.DigitalInOut(board.GP2),
            4: digitalio.DigitalInOut(board.GP3),
            5: digitalio.DigitalInOut(board.GP5),
            6: digitalio.DigitalInOut(board.GP4),
            7: digitalio.DigitalInOut(board.GP6),
            8: digitalio.DigitalInOut(board.GP7),
            9: digitalio.DigitalInOut(board.GP8),
            10: digitalio.DigitalInOut(board.GP9)
        }

        self.client_mapping = {
            1: self.lights[1],
            2: self.lights[2],
            3: self.lights[3],
            4: self.lights[4],
            5: self.lights[5],
            6: self.lights[6],
            7: self.lights[7],
            8: self.lights[8],
            9: self.lights[9],
            10: self.lights[10]
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
        self.client = WiFiClient("GuessRoulette", "password123", 0)
        
        # Once connected, clear screen
        if self.client.connected:
            self.display.clear()


    def turn_off_all_lights(self):
        for light in self.lights.values():
            light.value = False


    async def main(self):
        last_heartbeat = time.monotonic()
        while self.running:
            current_time = time.monotonic()
            if current_time - last_heartbeat >= 5.0:
                try:
                    if self.client.connected:
                        self.client.sock.send(b"heartbeat")
                        self.client.sock.settimeout(4)
                        buffer = bytearray(1024)
                        bytes_read = self.client.sock.recv_into(buffer)
                        if bytes_read:
                            response = buffer[:bytes_read].decode()
                            if response.strip() == "ok":
                                print("Heartbeat acknowledged")
                                last_heartbeat = current_time
                            else:
                                raise Exception("Unexpected heartbeat response")
                        else:
                            raise Exception("No heartbeat response")
                    else:
                        raise Exception("Client not connected")
                except Exception as e:
                    print(f"Heartbeat failed: {e}")
                    self.client.connected = False
                    self.client._connect()
                # recieve data, if data is recieved, process it
                data = self.client.receive_from_server()
                if data:
                    print(f"Data received: {data}")
                    if data.startswith("clients:"):
                        self.clients = [int(x) for x in data.split(":")[1].strip("[]").split(",")]
                        if "0" in self.clients:
                            self.clients.remove("0")
                        print(f"Clients: {self.clients}")
                    elif data.startswith("light_wheel:"):
                        if "[" in data:
                            self.choices = [int(x) for x in data.split(":")[1].strip("[]").split(",")]
                            self.light_wheel(self.choices, double_choice=True)
                            self.client.send("light_wheel:done")
                        elif "off" in data:
                            self.turn_off_all_lights()
                        else:
                            choice = int(data.split(":")[1])
                            self.light_wheel(choice, double_choice=False)
                    elif data.startswith("display:"):
                        pass
                    elif data.startswith("win"):
                        self.win()
                    elif "ok" in data:
                        pass
                    else:
                        print(f"Unknown data: {data}")


                if not self.started:
                    for client in self.clients:
                        if int(client) in int(self.lights.keys()):
                            self.lights[client].value = True
                else:
                    self.turn_off_all_lights()


                if self.start.value:
                    self.turn_off_all_lights()
                    self.started = True
                    self.client.send("start")

                await asyncio.sleep(0.1)

    def win(self):
        asyncio.run(self.audio.play_tracks(self.audio.tracks()))
        times = 15
        for _ in range(times/2):
            for light in self.lights.values():
                light.value = True
            
            time.sleep(0.5)
            self.turn_off_all_lights()

if __name__ == "__main__":
    console = Console()
    asyncio.run(console.main())
    
