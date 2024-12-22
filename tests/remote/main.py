from http.server import HTTPServer, BaseHTTPRequestHandler
import socket
import threading
import json
import time

# Global state to share between servers
class GameState:
    def __init__(self):
        self.clients = {}
        self.client_pins = {}

class GameTestServer:
    def __init__(self):
        self.state = GameState()
        
        # Start TCP server for game clients
        self.game_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.game_sock.bind(('0.0.0.0', 8080))
        self.game_sock.listen(10)
        
        # Configure HTTP handler with state access
        class ConfiguredHandler(WebInterfaceHandler):
            game_state = self.state
            
        self.http_server = HTTPServer(('0.0.0.0', 8000), ConfiguredHandler)
        
        print("Game server running on port 8080")
        print("Web interface on http://localhost:8000")
        
        threading.Thread(target=self.accept_clients).start()
        threading.Thread(target=self.http_server.serve_forever).start()

    def accept_clients(self):
        while True:
            client, addr = self.game_sock.accept()
            threading.Thread(target=self.handle_client, args=(client, addr)).start()

    def handle_client(self, client, addr):
        client_id = None
        try:
            client.settimeout(30)
        
            print(f"New connection from {addr}")
            data = client.recv(1024).decode()
            if data.startswith('id:'):
                client_id = int(data.split(':')[1])
                print(f"Client {client_id} connected from {addr}")
                
                self.state.clients[client_id] = client
                client.send(b"ok")
                
                print(f"Sending identification request to client {client_id}")
                time.sleep(0.1)
                client.send(b"iden")
                
                print(f"Waiting for client {client_id} acknowledgment")
                response = client.recv(1024).decode()
                if response == "ok":
                    pin = len(self.state.clients)
                    self.state.client_pins[client_id] = pin
                    print(f"Assigned pin {pin} to client {client_id}")
                    client.send(f"iden:{pin}".encode())
                
                # Keep connection alive
                # Keep connection alive
                while True:
                    try:
                        data = client.recv(1024).decode()
                        time.sleep(0.05)
                        if not data:
                            print(f"Client {client_id} disconnected (no data)")
                            break
                            
                        # Handle different message types
                        if data == "heartbeat":
                            #client.send(b"ok")  # Acknowledge heartbeat
                            pass
                        elif data.startswith("pick:"):
                            print(f"Received pick from client {client_id}: {data}")
                            client.send(b"ok")  # Acknowledge pick
                        elif data.startswith("guess+"):
                            print(f"Received guess from client {client_id}: {data}")
                            client.send(b"ok")  # Acknowledge guess
                        elif data.startswith("bet+"):
                            print(f"Received bet from client {client_id}: {data}")
                            client.send(b"ok")  # Acknowledge bet
                        elif data != "ok":  # Don't print 'ok' responses
                            print(f"Received from client {client_id}: {data}")
                            client.send(b"ok")
                            
                    except socket.timeout:
                        continue  # Keep waiting for messages
                    except Exception as e:
                        print(f"Error handling client {client_id} message: {e}")
                        break
                    
        except Exception as e:
            print(f"Client {client_id} error: {e}")
        finally:
            if client_id in self.state.clients:
                print(f"Removing client {client_id}")
                del self.state.clients[client_id]
                del self.state.client_pins[client_id]
            client.close()

class WebInterfaceHandler(BaseHTTPRequestHandler):
    game_state = None  # Will be set by ConfiguredHandler

    def log_message(self, format, *args):
        # if the message starts with 120, then pass
        if args[0].startswith('127'):
            return
        
    def safe_write(self, data):
        try:
            self.wfile.write(data)
        except (ConnectionAbortedError, BrokenPipeError) as e:
            print(f"Connection closed by client: {e}")
        except Exception as e:
            print(f"Error writing response: {e}")

    
    def do_GET(self):
        try:
            if self.path == '/':
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                
                html = """
                <html>
                <body>
                    <h2>Game Test Server</h2>
                    <h3>Connected Clients:</h3>
                    <pre id="clients"></pre>
                    <hr>
                    <h3>Quick Commands:</h3>
                    <button onclick="sendQuickCommand('start')">Send Start</button>
                    <button onclick="sendQuickCommand('role:2')">Set Picker</button>
                    <button onclick="sendQuickCommand('role:3+1')">Set Guesser</button>
                    <button onclick="sendQuickCommand('role:4+1')">Set Bet Maker</button>
                    <button onclick="sendQuickCommand('role:5')">Set Dead</button>
                    <button onclick="sendQuickCommand('win')">Win</button>
                    <button onclick="sendQuickCommand('health:50')">Health 50</button>
                    <button onclick="sendQuickCommand('health:0')">Health 0</button>
                    <button onclick="sendQuickCommand('health:100')">Health 100</button>
                    <button onclick="sendQuickCommand('clear')">clear</button>
                    <button onclick="sendQuickCommand('exit')">exit</button>
                    <hr>
                    <h3>Custom Command:</h3>
                    <select id="client">
                        <option value="all">All Clients</option>
                    </select>
                    <input type="text" id="command">
                    <button onclick="sendCommand()">Send</button>
                    
                    <script>
                        function sendQuickCommand(cmd) {
                            fetch('/send', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({client: 'all', command: cmd})
                            });
                        }
                        
                        function sendCommand() {
                            const client = document.getElementById('client').value;
                            const cmd = document.getElementById('command').value;
                            fetch('/send', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({client, command: cmd})
                            });
                        }
                        
                        function updateClients() {
                            fetch('/clients')
                                .then(r => r.json())
                                .then(data => {
                                    document.getElementById('clients').textContent = 
                                        JSON.stringify(data, null, 2);
                                    
                                    const select = document.getElementById('client');
                                    const currentValue = select.value;
                                    select.innerHTML = '<option value="all">All Clients</option>';
                                    data.clients.forEach(id => {
                                        select.innerHTML += `<option value="${id}">Client ${id}</option>`;
                                    });
                                    select.value = currentValue;
                                });
                        }
                        
                        setInterval(updateClients, 1000);
                    </script>
                </body>
                </html>
                """
                self.safe_write(html.encode())
            
            elif self.path == '/clients':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    
                    status = {
                        'clients': list(self.game_state.clients.keys()),
                        'pins': self.game_state.client_pins
                    }
                    self.safe_write(json.dumps(status).encode())
        except Exception as e:
            print(f"Error handling GET request: {e}")
    
    def do_POST(self):
        try:
            if self.path == '/send':
                length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(length).decode()
                print(f"Received POST data: {post_data}")
                data = json.loads(post_data)
                
                if data['client'] == 'all':
                    for client in self.game_state.clients.values():
                        client.send(data['command'].encode())
                else:
                    client_id = int(data['client'])
                    if client_id in self.game_state.clients:
                        self.game_state.clients[client_id].send(data['command'].encode())
                
                self.send_response(200)
                self.end_headers()
                self.safe_write(b"OK")
        except Exception as e:
            print(f"Error handling POST request: {e}")
            self.send_response(500)
            self.end_headers()

if __name__ == '__main__':
    server = GameTestServer()