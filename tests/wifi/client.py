import wifi
import socketpool
import random
import time


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
                        self.sock.connect(("192.168.4.1", 8080))

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


if __name__ == "__main__":
    role = None
    client = WiFiClient("GuessRoulette", "password", 1)
    try:
        client.send("Hello from client")
        while True:
            server_data = client.receive_from_server()
            if server_data:
                print(f"Data from server: {server_data}")
            if server_data is not None and server_data.startswith("role"):
                role = server_data.split(':')[1]
                time.sleep(1)
                client.send(f"pick:{random.randint(1, 100)}")
            
    except KeyboardInterrupt:
        client.close()
