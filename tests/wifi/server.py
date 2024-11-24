import wifi
import socketpool
import time


class WiFiServer:
    def __init__(self, ssid, password, max_clients=10):
        self.ssid = ssid
        self.password = password
        self.max_clients = max_clients
        self.clients = {}
        self.running = True

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

    def update(self):
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
                self._handle_new_client(conn, addr)
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

    @staticmethod
    def _handle_http(conn):
        try:
            conn.settimeout(1.0)
            buffer = bytearray(1024)
            bytes_read = conn.recv_into(buffer)
            if bytes_read:
                request = buffer[:bytes_read].decode()
                if 'GET' in request:
                    html = """
					<!DOCTYPE html>
					<html>
					<body>
						<h1>Pico W Server</h1>
						<p>This is a private network for IoT devices.</p>
					</body>
					</html>
					"""
                    response = 'HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n' + html
                    conn.send(response.encode())
        except Exception as e:
            print(f"HTTP connection error: {e}")
        finally:
            conn.close()

    def _handle_new_client(self, conn, addr):
        """Handle new incoming client connection"""
        try:
            conn.settimeout(5.0)
            buffer = bytearray(1024)
            bytes_read = conn.recv_into(buffer)
            if bytes_read:
                data = buffer[:bytes_read].decode()
                if data.startswith('id'):
                    client_id = int(data.split()[1])
                    # Close existing connection if any
                    if client_id in self.clients:
                        old_conn, _ = self.clients[client_id]
                        old_conn.close()
                    self.clients[client_id] = (conn, addr)
                    print(f"Client {client_id} registered from {addr}")
                    conn.send(b"ok")
                    conn.setblocking(False)
                else:
                    print("Invalid client registration data")
                    conn.close()
            else:
                print("No data received from client")
                conn.close()
        except Exception as e:
            print(f"New client connection error: {e}")
            conn.close()

    def _handle_data(self, client_id, data):
        """Handle received data from clients"""
        print(f"Received from client {client_id}: {data}")

    def _remove_client(self, client_id):
        """Remove a client from the connection pool"""
        try:
            conn, _ = self.clients.pop(client_id, (None, None))
            if conn:
                conn.close()
        except Exception as e:
            print(f"Error removing client {client_id}: {e}")
        print(f"Client {client_id} disconnected")

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


if __name__ == "__main__":
    server = WiFiServer("PicoNet", "123456789")
    try:
        while True:
            server.update()
            time.sleep(0.01)
    except KeyboardInterrupt:
        server.close()
