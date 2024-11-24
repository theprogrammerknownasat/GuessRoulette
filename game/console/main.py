import random
import inspect
import time

import wifi
import socketpool
import board
import digitalio
import rotaryio


class WiFiServer:
    def __init__(self, ssid, password, max_clients=10, game_instance=None):
        self.ssid = ssid
        self.password = password
        self.max_clients = max_clients
        self.clients = {}
        self.running = True
        self.data_log = []
        self.game_instance = game_instance

        # Initialize AP
        wifi.radio.stop_ap()
        wifi.radio.stop_station()
        time.sleep(1)

        # Start AP
        wifi.radio.start_ap(ssid=self.ssid, password=self.password)
        print("Access point active")
        print("Network config:", wifi.radio.ipv4_address_ap)

        pool = socketpool.SocketPool(wifi.radio)

        # HTTP Socket
        self.http_sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
        self.http_sock.bind((str(wifi.radio.ipv4_address_ap), 80))
        self.http_sock.listen(4)
        self.http_sock.settimeout(0.1)

        # Client Socket
        self.client_sock = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
        self.client_sock.bind((str(wifi.radio.ipv4_address_ap), 8080))
        self.client_sock.listen(self.max_clients)
        self.client_sock.settimeout(0.1)

        print("Server listening on ports 80 (HTTP) and 8080 (Clients)...")

    def update(self, accepting_players=True):
        """Process connections and handle data"""
        try:
            # Accept new HTTP connections
            try:
                conn, addr = self.http_sock.accept()
                self._handle_http(conn)
            except OSError:
                pass

            # Accept new client connections
            try:
                conn, addr = self.client_sock.accept()
                self._handle_new_client(conn, addr, accepting_players)
            except OSError:
                pass

            # Handle existing clients
            for client_id in list(self.clients.keys()):
                try:
                    conn, _ = self.clients[client_id]
                    conn.setblocking(False)
                    buffer = bytearray(1024)
                    try:
                        bytes_read = conn.recv_into(buffer)
                        if bytes_read:
                            data = buffer[:bytes_read].decode()
                            self._handle_data(client_id, data)
                    except OSError:
                        pass
                except Exception as e:
                    print(f"Client {client_id} error: {e}")
                    self._remove_client(client_id)

        except Exception as e:
            print(f"Update error: {e}")

    def _handle_new_client(self, conn, addr, accepting_players):
        """Handle new incoming client connection"""
        try:
            conn.settimeout(5.0)
            buffer = bytearray(1024)
            bytes_read = conn.recv_into(buffer)
            if bytes_read:
                data = buffer[:bytes_read].decode()
                if data.startswith('id'):
                    client_id = int(data.split(':')[1])
                    if client_id in self.clients or accepting_players:
                        # Close existing connection if any
                        if client_id in self.clients:
                            old_conn, _ = self.clients[client_id]
                            old_conn.close()
                        self.clients[client_id] = (conn, addr)
                        print(f"Client {client_id} registered from {addr}")
                        conn.send(b"ok")
                        conn.setblocking(False)
                    else:
                        print(f"Client {client_id} not allowed to join")
                        conn.send(b"exit")
                        conn.close()
                else:
                    print("Invalid client registration data")
                    conn.close()
            else:
                print("No data received from client")
                conn.close()
        except Exception as e:
            print(f"New client connection error: {e}")
            conn.close()

    def send_to_client(self, client_id, data):
        """Send data to a specific client and wait for 'ok' back."""
        try:
            if client_id in self.clients:
                conn, addr = self.clients[client_id]
                conn.setblocking(True)
                conn.send(data.encode())

                buffer = bytearray(1024)
                bytes_read = conn.recv_into(buffer)
                if bytes_read:
                    response = buffer[:bytes_read].decode()
                    if response.strip() == "ok":
                        print(f"Received 'ok' from client {client_id}")
                    else:
                        print(f"Unexpected response from client {client_id}: {response}")
                else:
                    print(f"No response from client {client_id}")

                conn.setblocking(False)
            else:
                print(f"Client {client_id} not connected")
        except Exception as e:
            print(f"Error sending data to client {client_id}: {e}")

    def _handle_http(self, conn):
        try:
            conn.settimeout(1.0)
            buffer = bytearray(1024)
            bytes_read = conn.recv_into(buffer)
            if bytes_read:
                request = buffer[:bytes_read].decode()
                if 'GET' in request:
                    # Retrieve all instance variables of the Game class
                    game_instance = self.game_instance  # Assuming the game instance is passed to the server
                    variables = {name: value for name, value in inspect.getmembers(game_instance) if
                                 not name.startswith('__') and not inspect.ismethod(value)}

                    # Create HTML content
                    html = "<!DOCTYPE html><html><body><h1>Game Variables</h1><table border='1'>"
                    for name, value in variables.items():
                        html += f"<tr><td>{name}</td><td>{value}</td></tr>"
                    html += "</table></body></html>"

                    response = 'HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n' + html
                    conn.send(response.encode())
        except Exception as e:
            print(f"HTTP connection error: {e}")
        finally:
            conn.close()

    def _handle_data(self, client_id, data):
        """Handle received data from clients"""
        self.data_log.append((client_id, data))

        try:
            conn, _ = self.clients[client_id]
            conn.setblocking(True)
            conn.send(b"ok")
            conn.setblocking(False)
        except Exception as e:
            print(f"Error sending acknowledgment to client {client_id}: {e}")

    def _remove_client(self, client_id):
        """Remove a client from the connection pool"""
        try:
            conn, _ = self.clients.pop(client_id, (None, None))
            if conn:
                conn.close()
        except Exception as e:
            print(f"Error removing client {client_id}: {e}")
        print(f"Client {client_id} disconnected")

    def get_data(self):
        """Retrieve and clear the data log"""
        data = self.data_log.copy()
        self.data_log.clear()
        return data

    def clear_data(self):
        """Clear the data log"""
        self.data_log.clear()

    def close(self):
        """Clean shutdown of server"""
        self.running = False
        for _, (conn, _) in self.clients.items():
            try:
                conn.close()
            except:
                pass
        self.clients.clear()
        self.http_sock.close()
        self.client_sock.close()
        wifi.radio.stop_ap()


class PlayerState:
    DEFAULT = 1
    PICKER = 2
    GUESSER = 3
    BETTER = 4
    DEAD = 5


class Player:
    def __init__(self, identifier: int):
        self.id = identifier
        self.state = PlayerState.DEFAULT
        self.bet = 0
        self.guess = 0
        self.health = 100


class Game:
    def __init__(self):
        self.guesser_2_num = None
        self.guesser_ids = None
        self.guesser_1_num = None
        self.players = []
        self.betters = []
        self.players_c = []
        self.wifi_keys = 0
        self.round = 0
        self.max_rounds = 1
        self.previous_wifi_keys = self.wifi_keys
        self.current_player = 0
        self.picker_num = 0
        self.clock = 0
        self.picker_id = None
        self.round_in_progress = False
        self.waiting_for_picker = False
        self.waiting_for_guessers = [False, False]
        self.waiting_for_betters = [False, False, False, False, False, False, False]

        self.server = WiFiServer("GuessRoulette", "password", game_instance=self)

        self.running = True
        self.accepting_players = True

        self.lights = {
            1: digitalio.DigitalInOut(board.GP16),
            2: digitalio.DigitalInOut(board.GP17),
            3: digitalio.DigitalInOut(board.GP18),
            4: digitalio.DigitalInOut(board.GP19),
            5: digitalio.DigitalInOut(board.GP20),
            6: digitalio.DigitalInOut(board.GP21),
            7: digitalio.DigitalInOut(board.GP22),
            8: digitalio.DigitalInOut(board.GP26),
            9: digitalio.DigitalInOut(board.GP27),
            10: digitalio.DigitalInOut(board.GP28),

        }

        self.encoder = rotaryio.IncrementalEncoder(board.GP14, board.GP15)
        self.encoder_counter = 0
        self.last_position = self.encoder.position

        for light in self.lights.values():
            light.direction = digitalio.Direction.OUTPUT
            light.value = True
            time.sleep(0.1)
            light.value = False

        self.start = digitalio.DigitalInOut(board.GP1)
        self.start.direction = digitalio.Direction.INPUT

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

    def io(self):
        position = self.encoder.position
        if position != self.last_position:
            self.encoder_counter += (position - self.last_position)
            self.last_position = position
            print(f"Encoder counter: {self.encoder_counter}")

    def run(self):
        while self.running:

            self.wifi_keys = len(list(self.server.clients.keys()))
            if self.wifi_keys != self.previous_wifi_keys:
                self.previous_wifi_keys = self.wifi_keys
                print(f"Connected players: {self.wifi_keys}")

            if self.start.value:
                self.accepting_players = False
                print("Game started")
                if self.wifi_keys < 3:
                    print("Not enough players")
                    self.accepting_players = True
                else:
                    for client_id in self.server.clients.keys():
                        self.players.append(Player(client_id))

            if not self.accepting_players:
                self.game()

            self.server.update(self.accepting_players)
            self.io()
            time.sleep(0.01)

    def game(self):
        # If there are less than 3 players living, end the game
        if len([player for player in self.players if player.state != PlayerState.DEAD]) < 3:
            winners = [player for player in self.players if player.state != PlayerState.DEAD]
            for winner in winners:
                self.server.send_to_client(winner.id, "win")
            time.sleep(60)
            if self.round < self.max_rounds:
                self.reset_game()
            else:
                for client_id in self.server.clients.keys():
                    self.server.send_to_client(client_id, "exit")
                self.server.close()
                self.running = False
                exit(0)
        if not self.waiting_for_picker and not any(self.waiting_for_guessers) and not any(self.waiting_for_betters):
            self.players_c = [player for player in self.players if player.state != PlayerState.DEAD]
            picker = self.choose_picker_and_betters()
            if picker:
                self.round += 1

                self.light_wheel(choice=picker.id)

                self.server.send_to_client(picker.id, f"role:{PlayerState.PICKER}")
                self.waiting_for_picker = True
                self.picker_id = picker.id

                for better in self.betters:
                    self.server.send_to_client(better.id, f"role:{PlayerState.BETTER}+{self.betters.index(better) + 1}")

        if self.waiting_for_picker:
            data_log = self.server.get_data()
            for client_id, data in data_log:
                if client_id == self.picker_id and data.startswith("pick:"):
                    try:
                        number = int(data.split(":")[1])
                        if 0 <= number <= 100:
                            self.picker_num = number
                            self.waiting_for_picker = False
                            print(f"Picker chose number: {self.picker_num}")
                            self.turn_off_all_lights()

                            guesser_1, guesser_2 = self.choose_guessers()
                            if guesser_1 and guesser_2:
                                self.light_wheel(choice=[guesser_1.id, guesser_2.id], double_choice=True)
                                self.server.send_to_client(guesser_1.id, f"role:{PlayerState.GUESSER}+1")
                                self.server.send_to_client(guesser_2.id, f"role:{PlayerState.GUESSER}+2")
                                self.waiting_for_guessers = [True, True]
                                self.guesser_ids = [guesser_1.id, guesser_2.id]
                                for better in self.betters:
                                    self.waiting_for_betters[self.betters.index(better)] = True
                        else:
                            print("Number out of range")
                    except ValueError:
                        print("Invalid number format")

        if any(self.waiting_for_guessers) or any(self.waiting_for_betters):
            data_log = self.server.get_data()
            for client_id, data in data_log:
                if client_id in self.guesser_ids and (data.startswith("guess+1:") or data.startswith("guess+2:")):
                    try:
                        number = int(data.split(":")[1])
                        if 0 <= number <= 100:
                            if data.startswith("guess+1:"):
                                self.guesser_1_num = number
                                self.waiting_for_guessers[0] = False
                            elif data.startswith("guess+2:"):
                                self.guesser_2_num = number
                                self.waiting_for_guessers[1] = False
                            print(f"Guesser {client_id} chose number: {number}")

                            if not any(self.waiting_for_guessers) and not any(self.waiting_for_betters):
                                self.turn_off_all_lights()
                                self.calculate_diff()
                                self.reset_game()
                        else:
                            print("Number out of range")
                    except ValueError:
                        print("Invalid number format")
                elif client_id in [better.id for better in self.betters] and data.startswith("bet+"):
                    try:
                        number = int(data.split(":")[1])
                        if 0 <= number <= 100:
                            better = [better for better in self.betters if better.id == client_id][0]
                            better.bet = number
                            self.waiting_for_betters[self.betters.index(better)] = False
                            print(f"Better {client_id} bet: {number}")

                            if not any(self.waiting_for_guessers) and not any(self.waiting_for_betters):
                                self.turn_off_all_lights()
                                self.calculate_diff()
                                self.reset_game()
                        else:
                            print("Number out of range")
                    except ValueError:
                        print("Invalid number format")

    def choose_picker_and_betters(self):
        if len(self.players_c) >= 3:
            picker = random.choice(self.players_c)
            self.players_c.remove(picker)
            picker.state = PlayerState.PICKER
            print(f"Picker: {picker.id}")

            self.betters = []
            for player in self.players_c:
                player.state = PlayerState.BETTER
                self.betters.append(player)
                print(f"Better: {player.id}")

            return picker
        else:
            print("Not enough players to start the game")
            return None

    def choose_guessers(self):
        if len(self.players_c) >= 2:
            guesser_1 = random.choice(self.players_c)
            self.players_c.remove(guesser_1)
            guesser_1.state = PlayerState.GUESSER
            print(f"Guesser 1: {guesser_1.id}")

            guesser_2 = random.choice(self.players_c)
            self.players_c.remove(guesser_2)
            guesser_2.state = PlayerState.GUESSER
            print(f"Guesser 2: {guesser_2.id}")

            return guesser_1, guesser_2
        else:
            print("Not enough players to choose guessers")
            return None, None

    def calculate_diff(self):
        picker_num = self.picker_num
        guesser_1_num = self.guesser_1_num
        guesser_2_num = self.guesser_2_num

        diff_1 = abs(picker_num - guesser_1_num)
        diff_2 = abs(picker_num - guesser_2_num)

        for better in self.betters:
            if abs(better.bet - picker_num) <= 10:
                better.health += 10
            elif abs(better.bet - picker_num) == 0:
                better.health += picker_num
            else:
                pass

        if diff_1 > diff_2:
            self.players[self.guesser_ids[0]].health -= diff_1
        elif diff_2 > diff_1:
            self.players[self.guesser_ids[1]].health -= diff_2
        elif diff_2 == 0 and diff_1 == 0:
            self.players[self.guesser_ids[0]].health = 100
            self.players[self.guesser_ids[1]].health = 100
        elif diff_2 == diff_1 and diff_1 != 0:
            print("Both guessers are equally close to the picker's number")
        else:
            print("Error calculating differences")

        print(f"Difference for Guesser 1: {diff_1}")
        print(f"Difference for Guesser 2: {diff_2}")

    def reset_game(self):

        for player in self.players:
            player.state = PlayerState.DEFAULT

        for player in self.players:
            self.server.send_to_client(player.id, "clear")

        all_ok = False
        while not all_ok:
            data_log = self.server.get_data()
            all_ok = all(
                client_id in [player.id for player in self.players] and data.strip() == "ok" for client_id, data in
                data_log)

        self.server.clear_data()

        self.round_in_progress = False
        self.waiting_for_picker = False
        self.waiting_for_guessers = [False, False]
        self.waiting_for_betters = [False] * len(self.betters)
        self.picker_id = None
        self.picker_num = 0
        self.guesser_1_num = None
        self.guesser_2_num = None
        self.guesser_ids = None

        self.game()


if __name__ == "__main__":
    game = Game()
    game.run()


"""
Client number order:
id:(client_id) -> server
start -> start
role:2 -> picker
role:4+(better_id) -> better
picker -> pick:number
role:3+1 -> guesser 1
role:3+2 -> guesser 2
guesser 1 -> guess+1:number
guesser 2 -> guess+2:number
better -> bet+(better_id):number
repeat
win -> win
(clear -> clear) | (exit -> exit)

"""