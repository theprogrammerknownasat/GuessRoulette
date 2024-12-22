import subprocess
import tkinter as tk
from tkinter import ttk
from http.server import HTTPServer, BaseHTTPRequestHandler
import socket
import threading
import json
import time
import ctypes
import sys
import os
import signal
import atexit

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def restart_as_admin():
    if not is_admin():
        print("Requesting admin privileges...")
        ctypes.windll.shell32.ShellExecuteW(
            None, 
            "runas", 
            sys.executable, 
            " ".join(['"' + sys.argv[0] + '"'] + sys.argv[1:]), 
            None, 
            1
        )
        sys.exit()

class WiFiHotspot:
    def __init__(self):
        if not is_admin():
            restart_as_admin()
        self.original_ssid = None
        self.original_key = None
        self.original_band = None
        self._get_original_settings()
        
        # Register cleanup handlers
        signal.signal(signal.SIGINT, self._cleanup)
        signal.signal(signal.SIGTERM, self._cleanup)
        atexit.register(self._cleanup)
        
    def _cleanup(self, *args):
        print("\nCleaning up hotspot...")
        self.stop_hotspot()
        sys.exit(0)

    def _get_original_settings(self):
        ps_command = '''
        Add-Type -AssemblyName System.Runtime.WindowsRuntime
        $TetheringManager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]
        $connectionProfile = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
        $manager = $TetheringManager::CreateFromConnectionProfile($connectionProfile)
        $config = $manager.GetCurrentAccessPointConfiguration()
        Write-Host "SSID:$($config.Ssid)"
        Write-Host "KEY:$($config.Passphrase)"
        Write-Host "BAND:$($config.Band)"
        '''
        result = subprocess.run(["powershell", "-Command", ps_command], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if line.startswith("SSID:"):
                self.original_ssid = line[5:].strip()
            elif line.startswith("KEY:"):
                self.original_key = line[4:].strip()
            elif line.startswith("BAND:"):
                self.original_band = line[5:].strip() or "TwoPointFourGigahertz"

    def start_hotspot(self, ssid="GuessRoulette", key="password123"):
        if not is_admin():
            print("❌ Admin privileges required")
            return False
            
        try:
            if self._test_network():
                self.stop_hotspot()
            ps_command = f'''
            $ErrorActionPreference = 'SilentlyContinue'
            Add-Type -AssemblyName System.Runtime.WindowsRuntime
            
            $connectionProfile = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
            if ($null -eq $connectionProfile) {{
                Write-Error "No active network connection found"
                exit 1
            }}
            Write-Host "Found active network profile"

            $TetheringManager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]
            $manager = $TetheringManager::CreateFromConnectionProfile($connectionProfile)
            if ($null -eq $manager) {{
                Write-Error "Failed to create tethering manager"
                exit 1
            }}
            Write-Host "Created tethering manager"
            
            # Configure hotspot
            $config = $manager.GetCurrentAccessPointConfiguration()
            $config.Ssid = "{ssid}"
            $config.Passphrase = "{key}"
            $config.Band = [Windows.Networking.NetworkOperators.TetheringWiFiBand]::TwoPointFourGigahertz
            Write-Host "Configured hotspot settings"
            
            # Apply configuration (errors suppressed)
            $null = $manager.ConfigureAccessPointAsync($config).AsTask().Wait()
            Write-Host "Applied configuration"
            
            # Start hotspot (errors suppressed)
            $null = $manager.StartTetheringAsync().AsTask().Wait()
            Write-Host "Started tethering"
            
            # Restore error preference
            $ErrorActionPreference = 'Continue'
            '''
            
            print(f"Starting Mobile Hotspot with SSID: {ssid}")
            result = subprocess.run(["powershell", "-Command", ps_command], 
                                capture_output=True, text=True)
            print(f"Setup output: {result.stdout}")
            if result.stderr:
                print(f"Setup errors: {result.stderr}")
            
            time.sleep(2)
            return self._test_network()
                
        except Exception as e:
            print(f"✗ Hotspot error: {str(e)}")
            return False

    def _test_network(self):
        ps_command = '''
        $network = Get-NetAdapter | Where-Object {$_.Name -like "*Local*"} | Select-Object Status
        Write-Host $network.Status
        '''
        result = subprocess.run(["powershell", "-Command", ps_command], 
                              capture_output=True, text=True)
        if "Up" in result.stdout:
            print("✓ Network is active")
            return True
        print("✗ Network is not active")
        return False
    
    def stop_hotspot(self):
        if not is_admin():
            print("❌ Admin privileges required")
            return False
        try:
            ps_command = f'''
            Add-Type -AssemblyName System.Runtime.WindowsRuntime
            
            $connectionProfile = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
            $TetheringManager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]
            $manager = $TetheringManager::CreateFromConnectionProfile($connectionProfile)
            
            # Stop tethering first
            $manager.StopTetheringAsync()
            Write-Host "Tethering stopped"
            
            # Reset configuration if we have original settings
            if ("{self.original_ssid}" -ne "" -and "{self.original_key}" -ne "") {{
                $config = $manager.GetCurrentAccessPointConfiguration()
                $config.Ssid = "{self.original_ssid}"
                $config.Passphrase = "{self.original_key}"
                $config.Band = [Windows.Networking.NetworkOperators.TetheringWiFiBand]::"{self.original_band}"
                $null = $manager.ConfigureAccessPointAsync($config)
                Write-Host "Reset to original settings"
            }}
            '''
            
            print("Stopping Mobile Hotspot...")
            result = subprocess.run(["powershell", "-Command", ps_command], 
                                capture_output=True, text=True)
            print(f"Stop output: {result.stdout}")
            if result.stderr:
                print(f"Stop errors: {result.stderr}")

            self._test_network()
            
            return True
                
        except Exception as e:
            print(f"✗ Stop hotspot error: {str(e)}")
            return False

class GUI:
    def __init__(self):
        
        self.state = GameState()

        
        # Create main window
        self.root = tk.Tk()
        self.root.title("Guess Roulette Server")
        self.setup_gui()
        
        # Network setup
        self.game_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.game_sock.bind(('0.0.0.0', 8080))
        self.game_sock.listen(10)
        
        class GameHandler(BaseHTTPRequestHandler):
            game_state = self.state
            
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                state_data = {
                    'clients': list(self.game_state.clients.keys()),
                    'round': self.game_state.round,
                    'game_active': self.game_state.game_in_progress
                }
                self.wfile.write(json.dumps(state_data).encode())
        
        self.http_server = HTTPServer(('0.0.0.0', 8000), GameHandler)
        
        # Start server threads
        threading.Thread(target=self.accept_clients, daemon=True).start()
        threading.Thread(target=self.http_server.serve_forever, daemon=True).start()

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
    def _on_closing(self):
        print("Closing server...")
        self.wifi.stop_hotspot()
        self.root.destroy()
        sys.exit(0)

    def setup_gui(self):
        # Controls frame
        controls = ttk.Frame(self.root, padding="5")
        controls.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        ttk.Button(controls, text="Start Hotspot", 
                   command=lambda: self.wifi.start_hotspot()).grid(row=0, column=0)
        ttk.Button(controls, text="Stop Hotspot",
                   command=lambda: self.wifi.stop_hotspot()).grid(row=0, column=1)
        
        # Status frame
        status = ttk.LabelFrame(self.root, text="Game Status", padding="5")
        status.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.players_var = tk.StringVar(value="Connected Players: 0")
        ttk.Label(status, textvariable=self.players_var).grid(row=0, column=0)

    def accept_clients(self):
        while True:
            client, addr = self.game_sock.accept()
            threading.Thread(target=self.handle_client, 
                           args=(client, addr), daemon=True).start()

    def handle_client(self, client, addr):
        client_id = None
        try:
            while True:
                data = client.recv(1024).decode()
                if not data:
                    break
                    
                if data.startswith('id:'):
                    client_id = int(data.split(':')[1])
                    self.state.clients[client_id] = client
                    client.send(b"ok")
                    self.update_gui()
                    
                elif data.startswith('pin:'):
                    pin = int(data.split(':')[1])
                    if client_id:
                        self.state.client_pins[client_id] = pin
                        
                # Add game logic handlers here
                
        except Exception as e:
            print(f"Client error: {e}")
        finally:
            if client_id and client_id in self.state.clients:
                del self.state.clients[client_id]
            client.close()
            self.update_gui()

    def update_gui(self):
        self.players_var.set(f"Connected Players: {len(self.state.clients)}")

    def run(self):
        self.root.mainloop()

class GameState:
    def __init__(self):
        self.clients = {}
        self.client_pins = {}
        self.max_rounds = 1
        self.started = False
        self.accepting_players = Tr\ue     #kjdfsvghgdzsfiouygf ukjsdyrbtio53w4iotuys ejkhgjdfbhsfdgkljg hdfkj g hdsfjklgh bh,mdfbh gjhtrkghdfkgjbhkjfgmbn,mfgnbkjdfg

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

class GameServer:
    def __init__(self):
        self.wifi = WiFiHotspot()
        self.state = GameState()
        
        # Start TCP server for game clients
        self.game_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.game_sock.bind(('0.0.0.0', 8080))
        self.game_sock.listen(10)

        self.log = []
        
        # Configure HTTP handler with state access
        #class ConfiguredHandler(WebInterfaceHandler):
            #game_state = self.state
            
        #self.http_server = HTTPServer(('0.0.0.0', 8000), ConfiguredHandler)
        
        print("Game server running on port 8080")
        #print("Web interface on http://localhost:8000")
        
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
                if client_id == str(0):
                    print("Console connected")
                    self.state.client_pins[client_id] = 0
                else:
                    print(f"Client {client_id} connected from {addr}")
                    
                    self.state.clients[client_id] = client
                    client.send(b"ok")
                    
                    print(f"Sending identification request to client {client_id}")
                    time.sleep(0.1)
                    client.send(b"iden")
                    
                    print(f"Waiting for client {client_id} acknowledgment")
                    response = client.recv(1024).decode()
                    if response == "ok":
                        start_time = time.monotonic()
                        cur_time = start_time
                        while cur_time - start_time < 5:
                            if 0 in self.state.clients:
                                data = self.state.clients[0].recv(1024).decode()
                                if data.startswith('idin:'):
                                    pin = int(data.split(':')[1])
                                    self.state.client_pins[client_id] = pin
                                    print(f"Assigned pin {pin} to client {client_id} from client 0")
                                    client.send(f"iden:{pin}".encode())
                                    break

                            else:
                                print("Console not connected, aborting connection")
                                client.send(b"reset")
                            cur_time = time.monotonic()
                            time.sleep(0.1)
                
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
                        else:
                            self.log.append(data)
                            if client_id == 0:
                                if data.startswith("start"):
                                    print(f"Received start from console: {data}")
                                    self.state.started = True
                                    client.send(b"ok")
                                elif data != "ok":  # Don't print 'ok' responses
                                    print(f"Received from client {client_id}: {data}")
                                    client.send(b"ok")

                            if data.startswith("pick:"):
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

    def send(self, id, message):
        try:
            if id in self.state.clients:
                self.state.clients[id].send(message.encode())
                return True
            else:
                print(f"Client {id} not found")
                return False
        except Exception as e:
            print(f"Error sending to client {id}: {e}")
            return False

        
class Game:
    def __init__(self):
        self.state = GameState()
        self.server = GameServer()

        self.guesser_1_num = None
        self.guesser_2_num = None
        self.players = []
        self.betters = []
        self.round = 0
        self.max_rounds = self.state.max_rounds

        self.num_players = len(self.state.clients)

        self.running = True

        threading.Thread(target=self.run).start()
    
    def run(self):
        while self.running:
            if self.num_players != len(self.state.clients):
                self.num_players = len(self.state.clients)
                print(f"Players: {self.num_players}")

            if self.state.started:
                self.state.accepting_players = False
                print("Game started")
                if self.num_players < 3:
                    print("Not enough players to start game")
                    self.state.started = False
                    self.state.accepting_players = True
                    time.sleep(1)
                    continue
                else:
                    for client in self.state.clients.keys():
                        self.players.append(Player(client))
                    for player in self.players:
                        self.server.send(player.id, "start")


if __name__ == "__main__":
    server = GameServer()
    server.run()