import subprocess
import tkinter as tk
from tkinter import messagebox
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
import random
import math
import winreg
import queue


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

def setup_wifi_peers_registry():
    reg_path = r"SYSTEM\CurrentControlSet\Services\icssvc\Settings"
    key_name = "WifiMaxPeers"
    default_value = 10
    
    try:
        # Try to open the key first
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path, 0, 
                            winreg.KEY_READ | winreg.KEY_WRITE)
    except WindowsError:
        # Key doesn't exist, create it
        key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
        messagebox.showwarning("Warning", "A reg key changing the number of devices that can connect to your PC's hotspot has been created or edited. Please restart your computer to apply changes!")
    
    try:
        # Try to read existing value
        value, _ = winreg.QueryValueEx(key, key_name)
    except WindowsError:
        # Value doesn't exist, create it
        winreg.SetValueEx(key, key_name, 0, winreg.REG_DWORD, default_value)
        messagebox.showwarning("Warning", "A reg key changing the number of devices that can connect to your PC's hotspot has been created or edited. Please restart your computer to apply changes! This program will now exit.")
        sys.exit()
    
    winreg.CloseKey(key)


class ClientHandler:
    def __init__(self, client, client_id):
        self.client = client
        self.client_id = client_id
        self.send_queue = queue.Queue()
        self.send_lock = threading.Lock()
        self.last_successful_comm = time.time()
        
    def send(self, data, max_retries=3):
        with self.send_lock:
            for attempt in range(max_retries):
                try:
                    self.client.settimeout(1.0)  # Short timeout for send
                    self.client.send(data if isinstance(data, bytes) else data.encode())
                    self.client.settimeout(2.0)  # Longer timeout for receive
                    response = self.client.recv(1024).decode()
                    if response.strip() == "ok":
                        self.last_successful_comm = time.time()
                        return True
                except Exception as e:
                    print(f"Send attempt {attempt + 1} failed: {e}") if attempt > 0 else None
                    time.sleep(0.1)  # Brief delay between retries
            return False


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

    @staticmethod
    def get_hotspot_ip():
        ps_command = '''
        Get-NetAdapter | 
        Where-Object {$_.Name -like "*Local Area Connection*" -and $_.Status -eq "Up"} |
        Get-NetIPAddress -AddressFamily IPv4 |
        Select-Object IPAddress |
        Format-Table -HideTableHeaders
        '''
        result = subprocess.run(["powershell", "-Command", ps_command],
                                capture_output=True, text=True)
        ip = result.stdout.strip()
        print(f"Hotspot IP: {ip}")
        return ip if ip else "192.168.137.1"  # Fallback to default

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
            $config.MaxClientCount = 12
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
            ip = self.get_hotspot_ip()
            print(f"""
            Network Ready:
            SSID: {ssid}
            Password: {key}
            IP: {ip}
            Port: 8080
            """)
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
    def __init__(self, gamestate, wifi):
        self.state = gamestate
        self.wifi = wifi

        # Create main window
        self.root = tk.Tk()
        self.root.title("Guess Roulette Server")
        self.setup_gui()

        self.ROLE_MAP = {
            "Default": PlayerState.DEFAULT,
            "Picker": PlayerState.PICKER,
            "Guesser": PlayerState.GUESSER,
            "Better": PlayerState.BETTER,
            "Dead": PlayerState.DEAD
        }

        self.status = None
        self.console_frame = None
        self.client_list = None

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _on_closing(self):
        print("Closing server...")
        # Close socket properly
        try:
            #self.game_sock.shutdown(socket.SHUT_RDWR)
            #self.game_sock.close()
            # Force close port on Windows
            #os.system(f'netsh int ipv4 delete excludedportrange protocol=tcp startport=8080 numberofports=1')
            self.wifi.stop_hotspot()
        except Exception as e:
            print(f"Error closing socket: {e}")
        self.root.destroy()
        exit(0)

    def setup_gui(self):
        # Main container
        main = ttk.Frame(self.root, padding="10")
        main.grid(row=0, column=0, sticky="nsew")
        self.root.title("Guess Roulette Server - Simple")

        # Status Section
        status = ttk.LabelFrame(main, text="Status", padding="5")
        status.grid(row=0, column=0, sticky="ew", pady=5)

        # Console status with circle
        self.console_light = tk.Canvas(status, width=20, height=20)
        self.console_light.grid(row=0, column=0, padx=5)
        self.indicator = self.console_light.create_oval(2, 2, 18, 18, fill='red')
        ttk.Label(status, text="Console").grid(row=0, column=1, padx=5)

        # Player count
        self.players_var = tk.StringVar(value="Players: 0")
        ttk.Label(status, textvariable=self.players_var).grid(row=0, column=2, padx=20)

        # Game Controls
        controls = ttk.LabelFrame(main, text="Game Controls", padding="5")
        controls.grid(row=1, column=0, sticky="ew", pady=5)

        # Start button and round counter
        ttk.Button(controls, text="Start Game",
                   command=lambda: self.send_all("start")).grid(row=0, column=0, padx=5)

        # Round counter
        round_frame = ttk.Frame(controls)
        round_frame.grid(row=0, column=1, padx=20)
        ttk.Label(round_frame, text="Rounds:").pack(side=tk.LEFT)
        self.round_count = tk.StringVar(value="1")
        ttk.Button(round_frame, text="-",
                   command=lambda: self.round_count.set(max(1, int(self.round_count.get()) - 1))
                   ).pack(side=tk.LEFT, padx=2)
        ttk.Label(round_frame, textvariable=self.round_count).pack(side=tk.LEFT, padx=5)
        ttk.Button(round_frame, text="+",
                   command=lambda: self.round_count.set(int(self.round_count.get()) + 1)
                   ).pack(side=tk.LEFT, padx=2)

        # Advanced mode button (small, right side)
        ttk.Button(main, text="A", width=3,
                   command=self.switch_to_advanced).grid(row=0, column=1,
                                                         sticky="ne", padx=5, pady=5)

    def switch_to_advanced(self):
        # Clear current window
        for widget in self.root.winfo_children():
            widget.destroy()
        # Setup advanced GUI
        self.setup_advanced_gui()
        self.root.title("Guess Roulette Server - Advanced")

    def switch_to_simple(self):
        # Clear current window
        for widget in self.root.winfo_children():
            widget.destroy()
        # Setup simple GUI
        self.setup_gui()
        self.root.title("Guess Roulette Server - Simple")

    def setup_advanced_gui(self):
        # Main container
        main = ttk.Frame(self.root, padding="10")
        main.grid(row=0, column=0, sticky="nsew")

        # Configure grid weights
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        # Status Bar
        status = ttk.LabelFrame(main, text="Server Status", padding="5")
        status.grid(row=0, column=0, columnspan=4, sticky="ew", pady=5)

        self.console_frame = ttk.Frame(status)
        self.console_frame.grid(row=0, column=0, sticky="w", padx=5)
        ttk.Label(self.console_frame, text="Console:").grid(row=0, column=0, padx=5)
        self.console_status = ttk.Label(self.console_frame, text="Disconnected", foreground="red")
        self.console_status.grid(row=0, column=1)

        # Game status
        ttk.Label(status, text="Game:").grid(row=0, column=2, padx=5)
        self.game_status = tk.StringVar(value="Stopped")
        ttk.Label(status, textvariable=self.game_status).grid(row=0, column=3)

        # Player count
        self.players_var = tk.StringVar(value="Players: 0")
        ttk.Label(status, textvariable=self.players_var).grid(row=0, column=4, padx=20)

        # Client Section
        clients = ttk.LabelFrame(main, text="Connected Clients", padding="5")
        clients.grid(row=1, column=0, sticky="nsew", padx=5)
        clients.grid_rowconfigure(0, weight=1)
        clients.grid_columnconfigure(0, weight=1)

        # Client list with scrollbar
        client_scroll = ttk.Scrollbar(clients)
        client_scroll.grid(row=0, column=1, sticky="ns")

        self.client_list = ttk.Treeview(clients,
                                        columns=("ID", "Role", "Health", "Pick"),
                                        selectmode="browse",
                                        yscrollcommand=client_scroll.set)
        self.client_list.grid(row=0, column=0, sticky="nsew")
        client_scroll.config(command=self.client_list.yview)

        # Configure columns
        self.client_list.column("#0", width=0, stretch=False)  # Hide first column
        self.client_list.column("ID", width=50)
        self.client_list.column("Role", width=100)
        self.client_list.column("Health", width=70)
        self.client_list.column("Pick", width=50)

        # Configure headings
        self.client_list.heading("ID", text="ID")
        self.client_list.heading("Role", text="Role")
        self.client_list.heading("Health", text="Health")
        self.client_list.heading("Pick", text="Pick")

        # Configure row height
        style = ttk.Style()
        style.configure('Treeview', rowheight=25)

        # Game Control Section
        controls = ttk.LabelFrame(main, text="Game Controls", padding="5")
        controls.grid(row=1, column=1, sticky="nsew", padx=5)

        # Game control buttons
        control_buttons = ttk.Frame(controls)
        control_buttons.grid(row=0, column=0, columnspan=2, pady=5)
        ttk.Button(control_buttons, text="Start Game",
                   command=lambda: self.send_all("start")).pack(side=tk.LEFT, padx=5)

        # Round counter
        round_frame = ttk.Frame(controls)
        round_frame.grid(row=1, column=0, columnspan=2, pady=5)
        ttk.Label(round_frame, text="Rounds:").pack(side=tk.LEFT, padx=5)
        self.round_count = tk.StringVar(value="1")
        ttk.Button(round_frame, text="-",
                   command=lambda: self.round_count.set(max(1, int(self.round_count.get()) - 1))
                   ).pack(side=tk.LEFT)
        ttk.Label(round_frame, textvariable=self.round_count).pack(side=tk.LEFT, padx=5)
        ttk.Button(round_frame, text="+",
                   command=lambda: self.round_count.set(int(self.round_count.get()) + 1)
                   ).pack(side=tk.LEFT)

        # Spinner controls
        spinner_frame = ttk.Frame(controls)
        spinner_frame.grid(row=2, column=0, columnspan=2, pady=5)
        ttk.Label(spinner_frame, text="Wheel ID:").pack(side=tk.LEFT, padx=5)
        self.wheel_id = tk.StringVar()
        ttk.Entry(spinner_frame, textvariable=self.wheel_id, width=5).pack(side=tk.LEFT, padx=5)
        ttk.Button(spinner_frame, text="Spin",
                   command=self.spin_wheel).pack(side=tk.LEFT, padx=5)
        ttk.Button(spinner_frame, text="Lights Off",
                   command=lambda: self.send_command("light_wheel:off")).pack(side=tk.LEFT, padx=5)

        # Enhanced virtual spinner
        spinner_frame = ttk.LabelFrame(controls, text="Virtual Spinner")
        spinner_frame.grid(row=0, column=0, columnspan=2, pady=5)

        self.spinner_canvas = tk.Canvas(spinner_frame, width=275, height=275)
        self.spinner_canvas.grid(row=0, column=0)
        self.draw_virtual_spinner(self.spinner_canvas)


        # Game State Section
        game_state = ttk.LabelFrame(main, text="Game State", padding="5")
        game_state.grid(row=2, column=0, columnspan=2, sticky="ew", pady=5)

        # Client Control Panel
        client_controls = ttk.LabelFrame(game_state, text="Client Controls", padding="5")
        client_controls.grid(row=3, column=0, columnspan=2, pady=5)

        # Client ID selector
        id_frame = ttk.Frame(client_controls)
        id_frame.grid(row=0, column=0, padx=5, pady=5)
        ttk.Label(id_frame, text="Client ID:").pack(side=tk.LEFT)
        self.client_id = tk.StringVar()
        ttk.Entry(id_frame, textvariable=self.client_id, width=5).pack(side=tk.LEFT, padx=5)

        # Health control
        health_frame = ttk.Frame(client_controls)
        health_frame.grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(health_frame, text="Health:").pack(side=tk.LEFT)
        self.health_val = tk.StringVar()
        ttk.Entry(health_frame, textvariable=self.health_val, width=5).pack(side=tk.LEFT, padx=5)

        def update_client():
            try:
                client_id = int(self.client_id.get())
                health = int(self.health_val.get())
                
                if client_id not in self.state.clients:
                    messagebox.showerror("Error", f"Client {client_id} not found")
                    return
                    
                if health <= 0:
                    messagebox.showerror("Error", "Health must be positive")
                    return

                # Update player health
                for player in self.state.players:
                    if player.id == client_id:
                        player.health = health
                        break

                cmd = f"health:{health}"
                print(f"Sending command: {cmd}")
                self.state.clients[client_id].send_(cmd)

            except ValueError:
                messagebox.showerror("Error", "Invalid input")

        ttk.Button(client_controls, text="Update Client", 
            command=update_client).grid(row=0, column=2, padx=5)


        # Command Section
        cmd_frame = ttk.LabelFrame(main, text="Manual Commands", padding="5")
        cmd_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=5)
        # Command boxes with labels
        ttk.Label(cmd_frame, text="Command:").grid(row=0, column=0, padx=2)
        self.cmd_entry = ttk.Entry(cmd_frame)
        self.cmd_entry.grid(row=0, column=1, sticky="ew", padx=5)
        
        ttk.Label(cmd_frame, text="Client ID:").grid(row=0, column=2, padx=2)
        self.client_entry = ttk.Entry(cmd_frame, width=5)
        self.client_entry.grid(row=0, column=3, sticky="w", padx=5)
        
        # Send buttons with fixed one-liner command
            # Then modify the button command:
        ttk.Button(cmd_frame, text="Send",
                command=lambda: self.send_to_client(
                    self.client_entry.get(),
                    self.cmd_entry.get())
        ).grid(row=0, column=4, padx=5)
        
        ttk.Button(cmd_frame, text="Send All", 
                  command=self.send_all
        ).grid(row=0, column=5, padx=5)

        ttk.Button(main, text="S", width=3,
                   command=self.switch_to_simple).grid(row=0, column=1,
                                                       sticky="ne", padx=5, pady=5)

    def draw_virtual_spinner(self, canvas):
        center_x, center_y = 137, 137
        radius = 100
        led_radius = 8

        # Rotate everything 90 degrees (π/2)
        rotation = math.pi / 2

        # Calculate vertex and edge points
        vertices = []
        led_points = []
        for i in range(10):
            # Vertex angles (with rotation)
            angle = (i * 2 * math.pi / 10) - (math.pi / 10) + rotation
            # Vertex points
            vx = center_x + radius * math.cos(angle)
            vy = center_y + radius * math.sin(angle)
            vertices.append((vx, vy))

            # LED points (middle of edges)
            led_angle = i * 2 * math.pi / 10 + rotation
            led_x = center_x + radius * math.cos(led_angle)
            led_y = center_y + radius * math.sin(led_angle)
            led_points.append((led_x, led_y))

        # Draw decagon edges
        for i in range(10):
            next_i = (i + 1) % 10
            canvas.create_line(vertices[i][0], vertices[i][1],
                               vertices[next_i][0], vertices[next_i][1],
                               fill='gray')

        # Draw LEDs with counterclockwise numbering from lower-left
        self.leds = {}
        for i in range(10):
            x, y = led_points[i]
            led = canvas.create_oval(
                x - led_radius, y - led_radius,
                x + led_radius, y + led_radius,
                fill='gray', tags=f'led{i}'
            )
            # Map physical LED numbers to visual positions (counterclockwise from lower-left)
            led_number = (8 - i) % 10 + 1
            self.leds[led_number - 1] = led  # Store with 0-based index

            # Number label with offset
            label_angle = i * 2 * math.pi / 10 + rotation
            label_x = x + 25 * math.cos(label_angle)
            label_y = y + 25 * math.sin(label_angle)
            canvas.create_text(label_x, label_y, text=str(led_number))

    def animate_wheel(self, choice=None, double_choice=False):
        def spin_to_choice(target, initial_speed=0.02, skip_light=None):
            speed = initial_speed
            spins = 2
            do_fake = random.random() < 0.25 and not skip_light

            for spin in range(spins):
                for i in range(10):
                    if i == skip_light:
                        continue

                    self.spinner_canvas.itemconfig(self.leds[i], fill='red')
                    self.root.update()
                    time.sleep(speed)
                    self.spinner_canvas.itemconfig(self.leds[i], fill='gray')

                    if spin == spins - 1 and i == target - 1 and do_fake:
                        self.spinner_canvas.itemconfig(self.leds[i], fill='red')
                        self.root.update()
                        time.sleep(0.3)
                        self.spinner_canvas.itemconfig(self.leds[i], fill='gray')
                        continue

                    if spin == spins - 1 and i == target:
                        self.spinner_canvas.itemconfig(self.leds[i], fill='red')
                        return

                speed *= 2.2

        # Turn off all LEDs
        for led in self.leds.values():
            self.spinner_canvas.itemconfig(led, fill='gray')

        if double_choice:
            # First spin
            spin_to_choice(choice[0], initial_speed=0.02)
            time.sleep(0.3)
            # Second spin
            spin_to_choice(choice[1], initial_speed=0.02, skip_light=choice[0])
        else:
            spin_to_choice(choice, initial_speed=0.02)

    def update_console_status(self):
        if "Simple" in self.root.title():
            if self.state.console_connected:
                self.console_light.itemconfig(self.indicator, fill='green')
            else:
                self.console_light.itemconfig(self.indicator, fill='red')
        else:
            if self.state.console_connected:
                self.console_status.configure(text="Connected", foreground="green")
            else:
                self.console_status.configure(text="Disconnected", foreground="red")

    def send_to_client(self, client_id, message):
        try:
            client_id = int(client_id)
            if client_id in self.state.clients:
                self.state.clients[client_id].send(message.encode())
                print(f"Sent to client {client_id}: {message}")
                return True
            else:
                print(f"Client {client_id} not found")
                return False
        except Exception as e:
            print(f"Error sending to client {client_id}: {e}")
            return False

    def send_all(self):
        retries = 2
        print(self.cmd_entry.get())
        while retries > 0:
            try:
                for client in self.state.clients:
                    print(f"Sending to client {client}: {self.cmd_entry.get()}")
                    self.state.clients[client].send(self.cmd_entry.get().encode())
                else:
                    break
            except RuntimeError as e:
                retries -= 1
                print(f"Error sending to all clients (retries left: {retries}): {e}")

    def spin_wheel(self):
        try:
            if "," in self.wheel_id.get():
                wheel_id = [int(x) for x in self.wheel_id.get().split(",")]
                id1, id2 = wheel_id
                self.animate_wheel([id1 - 1, id2 - 1], double_choice=True)
                self.send_to_client(0, f"light_wheel:[{id1 - 1},{id2 - 1}]")
            else:
                wheel_id = int(self.wheel_id.get())
                self.animate_wheel(wheel_id - 1)
                self.send_to_client(0, f"light_wheel:{wheel_id}")
        except ValueError:
            print("Invalid wheel ID")

    def update_client_list(self):
        # Clear existing items
        if self.client_list is not None:
            for item in self.client_list.get_children():
                self.client_list.delete(item)

            # Add all clients except console (ID 0)
            tries = 3
            while tries > 0:
                try:
                    for client_id in self.state.clients:
                        if client_id != 0:  # Skip console
                            # Find player object for this client
                            player = next((p for p in self.state.players if p.id == client_id), None)

                            if player:
                                role = "Default"
                                if player.state == PlayerState.PICKER:
                                    role = "Picker"
                                elif player.state == PlayerState.GUESSER:
                                    role = "Guesser"
                                elif player.state == PlayerState.BETTER:
                                    role = "Better"
                                elif player.state == PlayerState.DEAD:
                                    role = "Dead"

                                # Insert client info
                                self.client_list.insert("", "end", values=(
                                    client_id,
                                    role,
                                    player.health if hasattr(player, 'health') else 100,
                                    player.guess if hasattr(player, 'guess') else ""
                                ))
                            else:
                                # New client without player object
                                self.client_list.insert("", "end", values=(
                                    client_id,
                                    "Default",
                                    100,
                                    ""
                                ))
                    else:
                        break
                except RuntimeError:
                    tries -= 1
                    print("Error updating client list, retrying...")
                    time.sleep(0.5)

    def update_gui(self):
        self.players_var.set(f"Players: {len(self.state.clients) - (1 if self.state.console_connected else 0)}")
        self.update_console_status()
        self.update_client_list()


class GameState:
    def __init__(self):
        self.clients = {}
        self.max_rounds = 1
        self.players = []
        self.started = False
        self.console_connected = False
        self.accepting_players = True  #\ue     #kjdfsvghgdzsfiouygf ukjsdyrbtio53w4iotuys ejkhgjdfbhsfdgkljg hdfkj g hdsfjklgh bh,mdfbh gjhtrkghdfkgjbhkjfgmbn,mfgnbkjdfg


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
    def __init__(self, gamestate, gui):
        self.state = gamestate
        self.gui = gui

        # Start TCP server for game clients
        self.game_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.game_sock.bind(('0.0.0.0', 8080))
        self.game_sock.listen(10)

        self.log = []
        self.current_log = []
        self.old_log = []

        # Configure HTTP handler with state access
        #class ConfiguredHandler(WebInterfaceHandler):
        #game_state = self.state

        #self.http_server = HTTPServer(('0.0.0.0', 8000), ConfiguredHandler)

        print("Game server running on port 8080")
        #print("Web interface on http://localhost:8000")

        threading.Thread(target=self.accept_clients).start()
        #threading.Thread(target=self.http_server.serve_forever).start()

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
                handler = ClientHandler(client, client_id)
                self.state.clients[client_id] = handler

                if str(client_id) == str(0):
                    self.state.console_connected = True
                    print("Console connected")
                    
                else:
                    print(f"Client {client_id} connected from {addr}")

                client.send(b"ok")

                while True:
                    try:
                        # Set a short timeout for recv
                        client.settimeout(0.1)
                        data = client.recv(1024).decode()
                        
                        if not data:
                            raise ConnectionResetError("No data")

                        print(f"DEBUG: Received raw data from client {client_id}: {data}") if ("heartbeat" not in data) and ("ok" not in data) else None

                        # Handle different message types
                        if "heartbeat" in data:
                            handler.send(b"ok")
                        else:
                            self.old_log.append(data)
                            self.log = self.old_log
                            self.current_log = self.log
                            
                            if client_id == 0:
                                if data.startswith("start"):
                                    print(f"Received start from console: {data}")
                                    self.state.started = True
                                elif "ok" not in data:
                                    print(f"Received from client {client_id}: {data}")

                            # Handle game commands
                            if data.startswith(("pick:", "guess+", "bet+")):
                                print(f"Received command from client {client_id}: {data}")
                            elif "ok" not in data:
                                print(f"Received from client {client_id}: {data}")

                            handler.send(b"ok")

                    except socket.timeout:
                        if time.time() - handler.last_successful_comm > 15.0:
                            raise ConnectionResetError("Client dead")
                        continue
                    except ConnectionResetError:
                        if client_id in self.state.clients:
                            del self.state.clients[client_id]
                            self.state.players = [p for p in self.state.players if p.id != client_id]
                            self.gui.update_gui()
                    except Exception as e:
                        print(f"Error handling client {client_id}: {e}")
                        if client_id in self.state.clients:
                            del self.state.clients[client_id]
                            # Remove associated player
                            self.state.players = [p for p in self.state.players if p.id != client_id]
                            # Update GUI
                            self.gui.update_gui()
                        break

        except Exception as e:
            print(f"Client {client_id} error: {e}")
        finally:
            if client_id in self.state.clients:
                try:
                    print(f"Removing client {client_id}")
                    del self.state.clients[client_id]
                except Exception as e:
                    print(f"Error removing client {client_id}: {e}")

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

    def close(self):
        self.game_sock.close()
        self.http_server.shutdown()

    def get_data(self):
        log = self.current_log
        return log

    def clear_data(self):
        self.current_log = []
        self.old_log = []


class Game:
    def __init__(self):
        self.state = GameState()

        self.wifi = WiFiHotspot()

        setup_wifi_peers_registry()

        self.wifi.start_hotspot()

        self.gui = GUI(self.state, self.wifi)

        self.server = GameServer(self.state, self.gui)

        self.guesser_1_num = None
        self.guesser_2_num = None
        self.picker_id = None
        self.picker_num = None
        self.waiting_for_guessers = [False, False]
        self.waiting_for_betters = [False * len(self.state.clients) - 3]
        self.waiting_for_picker = False
        self.players = []
        self.betters = []
        self.players_c = []
        self.round = 0
        self.max_rounds = self.state.max_rounds

        self.num_players = len(self.state.clients)

        self.running = True

        self.state.players = self.players

        threading.Thread(target=self.run).start()
        self.gui.root.mainloop()

    def run(self):
        cur_time = time.monotonic()
        while self.running:
            if time.monotonic() - cur_time > 1:
                self.gui.update_gui()
                cur_time = time.monotonic()
            if self.num_players != len(self.state.clients):
                self.num_players = len(self.state.clients)
                self.state.players = self.players
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

            if not self.state.accepting_players:
                self.game()

            time.sleep(0.01)

    def game(self):
        # send dead role to dead players
        for player in self.players:
            if player.state == PlayerState.DEAD:
                self.server.send(player.id, f"role:{PlayerState.DEAD}")
        # If there are less than 3 players living, end the game
        if len([player for player in self.players if player.state != PlayerState.DEAD]) < 3:
            winners = [player for player in self.players if player.state != PlayerState.DEAD]
            if len(winners) == 2:
                winner = max(winners, key=lambda player: player.health)
                self.server.send(winner.id, "win")
                print(f"Player {winner.id} wins")
            elif len(winners) == 1:
                self.server.send(winners[0].id, "win")
                print(f"Player {winners[0].id} wins")
            else:
                pass

            time.sleep(15)

        if self.round < self.max_rounds:
            self.reset_game()
        else:
            winner = max(self.players, key=lambda player: player.health)
            self.server.send(winner.id, "win")
            time.sleep(15)
            for client_id in self.server.clients.keys():
                self.server.send(client_id, "off")
            self.server.close()
            self.running = False
            exit(0)

        if not self.waiting_for_picker and not any(self.waiting_for_guessers) and not any(self.waiting_for_betters):
            self.players_c = [player for player in self.players if player.state != PlayerState.DEAD]
            picker = self.choose_picker_and_betters()
            if picker:
                self.round += 1

                self.server.send(0, f"light_wheel:{picker.id}")
                # wait for id 0 to send back light_wheel:done
                start_time = time.monotonic()
                while True:
                    if time.monotonic() - start_time > 5:  # 5 second timeout
                        print("Timeout waiting for light_wheel:done")
                        break

                    if 0 not in self.server.state.clients:
                        print("Client 0 not connected")
                        break

                    try:
                        data = self.server.state.clients[0].recv(1024).decode()
                        if data == "light_wheel:done":
                            print("Light wheel animation completed")
                            break
                        else:
                            print(f"Received unexpected data from client 0: {data}")
                    except Exception as e:
                        print(f"Error receiving data: {e}")
                        break

                    time.sleep(0.1)

                self.server.send(picker.id, f"role:{PlayerState.PICKER}")
                self.waiting_for_picker = True
                self.picker_id = picker.id

                for better in self.betters:
                    self.server.send(better.id, f"role:{PlayerState.BETTER}+{self.betters.index(better) + 1}")
        else:
            print("I have no idea how this happened")

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
                            self.server.send(0, "light_wheel:off")

                            guesser_1, guesser_2 = self.choose_guessers()
                            if guesser_1 and guesser_2:
                                self.server.send(0, f"light_wheel:[{guesser_1.id}, {guesser_2.id}]")
                                self.server.send(guesser_1.id, f"role:{PlayerState.GUESSER}+1")
                                self.server.send(guesser_2.id, f"role:{PlayerState.GUESSER}+2")
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
                                self.server.send(0, "light_wheel:off")
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
                                self.server.send(0, "light_wheel:off")
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
            if better.bet == 0:
                print(f"Better {better.id} did not bet")
            else:
                if abs(better.bet - picker_num) <= 10:
                    better.health += 10
                elif abs(better.bet - picker_num) == 0:
                    better.health += picker_num
                elif abs(better.bet - picker_num) <= 70:
                    better.health -= abs(better.bet - picker_num)
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

        # send updated health to players
        for player in self.players:
            self.server.send_to_client(player.id, f"health:{player.health}")

            if player.health <= 0:
                player.state = PlayerState.DEAD

        print(f"Difference for Guesser 1: {diff_1}")
        print(f"Difference for Guesser 2: {diff_2}")

    def reset_game(self):
        # Reset player states
        for player in self.players:
            player.state = PlayerState.DEFAULT if player.state != PlayerState.DEAD else PlayerState.DEAD

        # Clear old data
        self.server.clear_data()
        
        # Send clear command and record time
        clear_time = time.time()
        for player in self.players:
            if player.id in self.state.clients:
                self.server.send(player.id, "clear")

        # Wait for new acknowledgments
        responded_players = set()
        while len(responded_players) < len([p for p in self.players if p.id in self.state.clients]):
            data_log = self.server.get_data()
            for client_id, data, timestamp in data_log:
                if (timestamp > clear_time and 
                    client_id in self.state.clients and 
                    data.strip() == "ok"):
                    responded_players.add(client_id)

        # Reset game state
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
