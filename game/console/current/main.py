import asyncio
import random
import time
import array
import math

import wifi
import socketpool
import board
import digitalio
import rotaryio
import pwmio
import adafruit_ssd1306


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

class AudioMixer:
    def __init__(self, audio_pos, audio_neg):
        self.audio_pos = audio_pos
        self.audio_neg = audio_neg
        self.sample_rate = 44100
        self.max_duty = 65535

    async def play_tone(self, frequencies):
        if not frequencies:
            self.audio_pos.duty_cycle = 0
            self.audio_neg.duty_cycle = 0
            return

        # Generate one period of mixed waveform
        samples = array.array('H', [0] * 100)
        t = [i/len(samples) for i in range(len(samples))]
        
        # Mix sine waves
        for i in range(len(samples)):
            mixed = sum(math.sin(2 * math.pi * f * t[i]) for f in frequencies)
            # Normalize and scale to PWM range
            normalized = (mixed / len(frequencies) + 1) / 2
            samples[i] = int(normalized * self.max_duty)

        # Output differential signals
        for sample in samples:
            self.audio_pos.duty_cycle = sample
            self.audio_neg.duty_cycle = self.max_duty - sample
            await asyncio.sleep(1/(self.sample_rate * len(samples)))

    async def play_tracks(self, tracks):
        start_time = time.monotonic()
        active_freqs = []

        # Find end time of longest track
        end_time = max(track[-1][1] for track in tracks)

        while (current_time := time.monotonic() - start_time) < end_time:
            # Get active frequencies from all tracks at current time
            active_freqs = []
            for track in tracks:
                # Find the current note in this track
                for i, (freq, timestamp) in enumerate(track):
                    if timestamp <= current_time:
                        if i + 1 < len(track) and track[i + 1][1] > current_time:
                            if freq > 0:
                                active_freqs.append(freq)
                            break

            await self.play_tone(active_freqs)
            await asyncio.sleep(0.01)  # Small delay for stability

        self.audio_pos.duty_cycle = 0
        self.audio_neg.duty_cycle = 0

    @staticmethod
    def tracks():
        return [[
            (0.00, 0.000000),
            (0.00, 0.000000),
            (0.00, 0.000000),
            (0.00, 0.000000),
            (0.00, 0.000000),
            (0.00, 0.000000),
            (0.00, 0.000000),
            (0.00, 0.000000),
            (440.00, 0.000000),
            (0.00, 0.187500),
            (493.88, 0.187500),
            (554.37, 0.375000),
            (0.00, 0.377604),
            (0.00, 0.593750),
            (440.00, 0.593750),
            (0.00, 0.781250),
            (440.00, 0.781250),
            (0.00, 0.968750),
            (493.88, 0.968750),
            (0.00, 1.187500),
            (554.37, 1.187500),
            (0.00, 1.406250),
            (440.00, 1.406250),
            (0.00, 1.593750),
            (440.00, 1.593750),
            (0.00, 1.781250),
            (415.30, 1.781250),
            (0.00, 1.968750),
            (369.99, 1.968750),
            (0.00, 2.187500),
            (415.30, 2.187500),
            (0.00, 2.375000),
            (440.00, 2.375000),
            (0.00, 2.531250),
            (493.88, 2.531250),
            (0.00, 2.750000),
            (415.30, 2.750000),
            (0.00, 2.937500),
            (329.63, 2.937500),
            (0.00, 3.125000),
            (440.00, 3.125000),
            (493.88, 3.312500),
            (0.00, 3.313802),
            (0.00, 3.500000),
            (554.37, 3.500000),
            (0.00, 3.656250),
            (440.00, 3.687500),
            (0.00, 3.872396),
            (440.00, 3.875000),
            (0.00, 4.062500),
            (493.88, 4.062500),
            (0.00, 4.250000),
            (554.37, 4.250000),
            (0.00, 4.468750),
            (440.00, 4.468750),
            (0.00, 4.656250),
            (440.00, 4.656250),
            (0.00, 4.843750),
            (415.30, 4.843750),
            (0.00, 5.062500),
            (369.99, 5.062500),
            (0.00, 5.218750),
            (493.88, 5.218750),
            (0.00, 5.468750),
            (415.30, 5.468750),
            (0.00, 5.625000),
            (329.63, 5.625000),
            (0.00, 5.812500),
            (440.00, 5.843750),
            (0.00, 6.250000),
            (880.00, 6.281250),
            (0.00, 6.468750),
            (987.77, 6.468750),
            (0.00, 6.687500),
            (1108.73, 6.687500),
            (0.00, 6.906250),
            (880.00, 6.906250),
            (0.00, 7.092448),
            (880.00, 7.093750),
            (0.00, 7.281250),
            (987.77, 7.281250),
            (0.00, 7.468750),
            (1108.73, 7.468750),
            (880.00, 7.687500),
            (0.00, 7.688802),
            (0.00, 7.875000),
            (880.00, 7.875000),
            (0.00, 8.059896),
            (830.61, 8.062500),
            (0.00, 8.250000),
            (739.99, 8.250000),
            (0.00, 8.468750),
            (830.61, 8.468750),
            (0.00, 8.656250),
            (880.00, 8.656250),
            (0.00, 8.843750),
            (987.77, 8.843750),
            (0.00, 9.031250),
            (830.61, 9.031250),
            (0.00, 9.250000),
            (659.26, 9.250000),
            (880.00, 9.437500),
            (0.00, 9.441406),
            (987.77, 9.593750),
            (0.00, 9.600260),
            (0.00, 9.812500),
            (1108.73, 9.812500),
            (0.00, 10.031250),
            (880.00, 10.031250),
            (0.00, 10.218750),
            (880.00, 10.218750),
            (0.00, 10.406250),
            (987.77, 10.406250),
            (0.00, 10.593750),
            (1108.73, 10.593750),
            (0.00, 10.750000),
            (987.77, 10.750000),
            (0.00, 10.937500),
            (880.00, 10.937500),
            (0.00, 11.125000),
            (830.61, 11.125000),
            (0.00, 11.312500),
            (739.99, 11.312500),
            (0.00, 11.500000),
            (987.77, 11.500000),
            (0.00, 11.687500),
            (830.61, 11.687500),
            (0.00, 11.875000),
            (659.26, 11.875000),
            (0.00, 12.093750),
            (880.00, 12.093750),
            (0.00, 12.907552),
            (0.00, 12.907552),
            (0.00, 12.907552),
            (0.00, 12.907552),
            (0.00, 12.907552),
            (0.00, 12.907552),
            (0.00, 12.907552),
            (0.00, 12.907552),
            (0.00, 12.907552),
            (0.00, 13.007552),
        ],
            [
                (220.00, 0.375000),
                (0.00, 0.968750),
                (220.00, 1.187500),
                (0.00, 1.781250),
                (146.83, 1.968750),
                (0.00, 2.375000),
                (164.81, 2.750000),
                (0.00, 3.312500),
                (220.00, 3.500000),
                (0.00, 4.093750),
                (220.00, 4.250000),
                (0.00, 4.843750),
                (146.83, 5.062500),
                (0.00, 5.468750),
                (164.81, 5.468750),
                (0.00, 5.625000),
                (220.00, 5.843750),
                (0.00, 6.250000),
                (440.00, 6.687500),
                (0.00, 7.312500),
                (440.00, 7.500000),
                (0.00, 8.062500),
                (293.66, 8.250000),
                (0.00, 8.875000),
                (329.63, 9.031250),
                (0.00, 9.670573),
                (440.00, 9.843750),
                (0.00, 10.406250),
                (440.00, 10.593750),
                (0.00, 11.125000),
                (293.66, 11.281250),
                (329.63, 11.656250),
                (0.00, 11.682292),
                (0.00, 11.875000),
                (440.00, 12.093750),
                (0.00, 12.906250),
                (0.00, 13.006250),
            ]]

class Console:
    def __init__(self):
        self.client = WiFiClient("GuessRoulette", "password123", 0)

        self.identification_pins = {
            1: digitalio.DigitalInOut(board.GP16),
            2: digitalio.DigitalInOut(board.GP17),
            3: digitalio.DigitalInOut(board.GP18),
            4: digitalio.DigitalInOut(board.GP19),
            5: digitalio.DigitalInOut(board.GP20),
            6: digitalio.DigitalInOut(board.GP21),
            7: digitalio.DigitalInOut(board.GP22),
            8: digitalio.DigitalInOut(board.GP26),
            9: digitalio.DigitalInOut(board.GP27),
            10: digitalio.DigitalInOut(board.GP28)
        }

        for pin in self.identification_pins.values():
            pin.direction = digitalio.Direction.INPUT

        self.identification_off = digitalio.DigitalInOut(board.GP11)
        self.identification_off.direction = digitalio.Direction.OUTPUT

        self.lights = {
            1: digitalio.DigitalInOut(board.GP0),
            2: digitalio.DigitalInOut(board.GP1),
            3: digitalio.DigitalInOut(board.GP2),
            4: digitalio.DigitalInOut(board.GP3),
            5: digitalio.DigitalInOut(board.GP4),
            6: digitalio.DigitalInOut(board.GP5),
            7: digitalio.DigitalInOut(board.GP6),
            8: digitalio.DigitalInOut(board.GP7),
            9: digitalio.DigitalInOut(board.GP8),
            10: digitalio.DigitalInOut(board.GP9)
        }

        for light in self.lights.values():
            light.direction = digitalio.Direction.OUTPUT
            light.value = True
            time.sleep(0.1)
            light.value = False

        self.speaker = {
            "pos": digitalio.DigitalInOut(board.GP17),
            "neg": digitalio.DigitalInOut(board.GP16)
        }

        self.start = digitalio.DigitalInOut(board.GP10)
        self.start.direction = digitalio.Direction.INPUT

        # setup i2c bus for display with sda and scl on gpio14 and 15
        i2c = board.I2C(14, 15)
        self.display = adafruit_ssd1306.SSD1306_I2C(128, 32, i2c)

        self.audio_pos = digitalio.DigitalInOut(board.GP12)
        self.audio_neg = digitalio.DigitalInOut(board.GP13)

        self.audio = AudioMixer(self.audio_pos, self.audio_neg)

        self.running = True

        self.clients = []
        self.choices = []

        self.started = False

    def light_wheel(self, choice=None, double_choice=False):
        if not choice:
            raise ValueError("No choice provided")

        if double_choice:
            if not isinstance(choice, list) or len(choice) != 2:
                raise ValueError("Choice must be a list of two values when double_choice is True")

            first_choice, second_choice = choice
            times = random.randint(4, 10)
            speed = 0.1

            # First spin
            for each in range(1, times + 1):
                for light_id, light in self.lights.items():
                    light.value = True
                    time.sleep(speed)
                    light.value = False

                    if each == times and light_id == first_choice - 1:
                        speed = 1
                    elif each == times and light_id == first_choice:
                        light.value = True
                        break
                if each < times - 5:
                    speed = 0.1
                else:
                    speed = 0.1
                if each < times - 3:
                    speed = 0.3
                elif each < times - 2:
                    speed = 0.5
                elif each < times - 1:
                    speed = 0.8

            # Second spin
            times = random.randint(4, 10)
            for each in range(1, times + 1):
                for light_id, light in self.lights.items():
                    if light_id != first_choice:
                        light.value = True
                    time.sleep(speed)
                    if light_id != first_choice:
                        light.value = False

                    if each == times and light_id == second_choice - 1:
                        speed = 1
                    elif each == times and light_id == second_choice:
                        light.value = True
                        return
                if each < times - 5:
                    speed = 0.1
                else:
                    speed = 0.1
                if each < times - 3:
                    speed = 0.3
                elif each < times - 2:
                    speed = 0.5
                elif each < times - 1:
                    speed = 0.8

        else:
            times = random.randint(4, 10)
            speed = 0.1

            for each in range(1, times + 1):
                for light_id, light in self.lights.items():
                    light.value = True
                    time.sleep(speed)
                    light.value = False

                    if each == times and light_id == choice - 1:
                        speed = 1
                    elif each == times and light_id == choice:
                        light.value = True
                        return
                if each < times - 5:
                    speed = 0.1
                else:
                    speed = 0.1
                if each < times - 3:
                    speed = 0.3
                elif each < times - 2:
                    speed = 0.5
                elif each < times - 1:
                    speed = 0.8


    def turn_off_all_lights(self):
        for light in self.lights.values():
            light.value = False

    def reset_identification(self):
        self.identification_off.value = True
        time.sleep(0.1)
        self.identification_off.value = False

    def handle_identification(self):

        active_pins = []
        for pin_id, pin in self.identification_pins.items():
            if pin.value:
                active_pins.append(pin_id)

        if len(active_pins) == 1:
            active_pin = active_pins[0]
            print(f"Active pin: {active_pin}")

            # Associate the active pin with the client ID
            self.client.send("idin:{active_pin}")
        elif len(active_pins) > 1:
            print("More than one pin is active")
            while len(active_pins) > 1:
                self.reset_identification()
                active_pins = []
                for pin_id, pin in self.identification_pins.items():
                    if pin.value:
                        active_pins.append(pin_id)

                if len(active_pins) == 1:
                    active_pin = active_pins[0]
                    print(f"Active pin: {active_pin}")

                    # Associate the active pin with the client ID
                    self.send(f"idin:{active_pin}")
        else:
            pass


    async def main(self):
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
                    self.client.connected = False
                    self.client._connect()

            self.handle_identification()

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
                    else:
                        choice = int(data.split(":")[1])
                        self.light_wheel(choice, double_choice=False)
                elif data.startswith("audio:"):
                    pass
                elif data.startswith("display:"):
                    pass
                elif data.startswith("win"):
                    self.win()
                elif data.startswith("rstidn"):
                    self.reset_identification()
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

    def win(self):
        asyncio.run(self.audio.play_tracks(self.audio.tracks()))
        times = 15
        for _ in range(times/2):
            for light in self.lights.values():
                light.value = True
            
            time.sleep(0.5)
            self.turn_off_all_lights()




"""
clients: should return the PINS

"""

