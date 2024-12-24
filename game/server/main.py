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
import paho.mqtt.client as mqtt
import asyncio

LIMITED = True

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

            New-NetFirewallRule -DisplayName "Mosquitto MQTT" -Direction Inbound -Protocol TCP -LocalPort 1883 -Action Allow

            net stop mosquitto
            net start mosquitto
            
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
        # Test network adapter
        ps_command = '''
        $network = Get-NetAdapter | Where-Object {$_.Name -like "*Local*"} | Select-Object Status
        Write-Host $network.Status
        '''
        result = subprocess.run(["powershell", "-Command", ps_command],
                                capture_output=True, text=True)
        if "Up" not in result.stdout:
            print("✗ Network is not active")
            return False
        print("✓ Network is active")
        return True


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
    def __init__(self, gamestate, wifi, server):
        self.state = gamestate
        self.wifi = wifi
        self.server = server

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

        ttk.Label(status, text="Limited Mode Enabled!", foreground="red").grid(row=0, column=3, padx=20) if LIMITED else None

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
        status.grid(row=0, column=0, columnspan=5, sticky="ew", pady=5)

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

        ttk.Label(status, text="Limited Mode Enabled!", foreground="red").grid(row=0, column=5, padx=20) if LIMITED else None

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

        ttk.Button(clients, text="Refresh", command=self.update_client_list).grid(row=1, column=0, pady=5)

        # Game Control Section
        controls = ttk.LabelFrame(main, text="Game Controls", padding="5")
        controls.grid(row=1, column=1, sticky="nsew", padx=5)

        # Game control buttons
        control_buttons = ttk.Frame(controls)
        control_buttons.grid(row=0, column=0, columnspan=2, pady=5)
        ttk.Button(control_buttons, text="Start Game",
                   command=lambda: start).pack(side=tk.LEFT, padx=5)
        
        def start():
            self.send_all("start")
            self.state.started = True
            self.state.accepting_players = False

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
                   command=lambda: self.server.send(0, json.dumps({"type": "light_wheel", "data": "off"}))).pack(side=tk.LEFT, padx=5)

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

        ttk.Button(client_controls, text="Update Client", 
            command=self.update_client).grid(row=0, column=2, padx=5)


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
                command=lambda: self.handle_command_send()
        ).grid(row=0, column=4, padx=5)
        
        ttk.Button(cmd_frame, text="Send All", 
                  command=self.send_all
        ).grid(row=0, column=5, padx=5)

        ttk.Button(main, text="S", width=3,
                   command=self.switch_to_simple).grid(row=0, column=1,
                                                       sticky="ne", padx=5, pady=5)
        
    def update_client(self):
        try:
            client_id = int(self.client_id.get())
            health = int(self.health_val.get())
            
            if health <= 0:
                messagebox.showerror("Error", "Health must be positive")
                return

            # Find and update player
            player = next((p for p in self.state.players if p.id == cli+30
                           .as_integer_ratio), None)
            if player:
                player.health = health
                self.server.send(client_id, json.dumps({
                    "type": "health",
                    "health": health
                }))
                self.update_client_list()
            else:
                messagebox.showerror("Error", f"Client {client_id} not found")

        except ValueError:
            messagebox.showerror("Error", "Invalid input")
        
    def handle_command_send(self, id=None, command=None):
        client_id = self.client_entry.get() if id is None else id
        command = self.cmd_entry.get() if id is None else command
        
        # Parse command and data
        cmd_parts = command.split(':')
        payload = {
            "type": cmd_parts[0],
            "data": cmd_parts[1] if len(cmd_parts) > 1 else None
        }
        
        self.server.send(client_id, json.dumps(payload))

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

    def send(self, client_id, message):
        self.handle_command_send(client_id, message)

    def send_all(self):
        self.server.broadcast(json.dumps({"type": f"{self.cmd_entry.get()}"}))

    def spin_wheel(self):
        try:
            if "," in self.wheel_id.get():
                wheel_id = [int(x) for x in self.wheel_id.get().split(",")]
                id1, id2 = wheel_id
                self.animate_wheel([id1 - 1, id2 - 1], double_choice=True)
                self.send(0, f"light_wheel:[{id1 - 1},{id2 - 1}]")
            else:
                wheel_id = int(self.wheel_id.get())
                self.animate_wheel(wheel_id - 1)
                self.send(0, f"light_wheel:{wheel_id}")
        except ValueError:
            print("Invalid wheel ID")

    def update_client_list(self):

        if self.client_list is None:
            return
            
        for item in self.client_list.get_children():
            self.client_list.delete(item)

        for client_id in self.state.clients:
            if client_id != 0:  # Skip console
                player = next((p for p in self.state.players if p.id == client_id), None)
                if not player:
                    continue
                    
                role = "Default"
                if player.state == PlayerState.PICKER:
                    role = "Picker"
                elif player.state == PlayerState.GUESSER:
                    role = "Guesser"
                elif player.state == PlayerState.BETTER:
                    role = "Better"
                elif player.state == PlayerState.DEAD:
                    role = "Dead"

                self.client_list.insert("", "end", values=(
                    client_id,
                    role,
                    player.health,
                    ""  # Pick column always empty in server view
                ))

    def update_gui(self):
        self.players_var.set(f"Players: {len(self.state.clients) - (1 if self.state.console_connected else 0)}")
        self.update_console_status()
        self.update_client_list()
        self.state.max_rounds = int(self.round_count.get())
        if not self.state.started:
            self.send(0, f"clients:[{self.state.clients.keys()}]")


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
        self.health = 100 if not LIMITED else 15


class GameServer:
    def __init__(self, game, gamestate, bind_address="192.168.137.1"):
        print("Starting Game Server...")
        self.state = gamestate
        self.game = game
        
        self.start_broker()

        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        self.wheel_response_received = threading.Event()
        self.wheel_done = False

        self.picker_response = threading.Event()
        self.picker_number = None
        self.guesser_responses = [threading.Event(), threading.Event()]
        self.guesser_numbers = [None, None]
        self.better_responses = {} 

        max_retries = 5
        retry_delay = 0.5

        self.last_pings = {}

        self.cleanup_running = True
        self.cleanup_thread = threading.Thread(target=self.cleanup_loop)
        self.cleanup_thread.daemon = True
        self.cleanup_thread.start()
        
        for attempt in range(max_retries):
            try:
                self.client.connect(bind_address, 1883, 60)
                self.client.loop_start()
                print(f"MQTT connected on attempt {attempt + 1}")
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"Connection attempt {attempt + 1} failed, retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    print(f"Failed to start MQTT client after {max_retries} attempts: {e}")
                    sys.exit(1)

    def start_broker(self):
        try:
            print("Starting Mosquitto MQTT broker...")
            # Check if port is in use
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            in_use = sock.connect_ex(('192.168.137.1', 1883)) == 0
            sock.close()
            
            if in_use:
                print("Port 1883 is in use, killing existing broker...")
                # Kill any existing mosquitto process
                subprocess.run(["taskkill", "/f", "/im", "mosquitto.exe"], 
                            capture_output=True)
                # Force close port on Windows
                subprocess.run(["netsh", "int", "ipv4", "delete", "excludedportrange", 
                            "protocol=tcp", "startport=1883", "numberofports=1"],
                            capture_output=True)
                time.sleep(3)  # Wait for cleanup
                
            # Create config file    
            config_content = """
    listener 1883
    allow_anonymous true
    persistence false
    bind_address 192.168.137.1
            """
            config_path = "mosquitto.conf"
            with open(config_path, "w") as f:
                f.write(config_content)
            
            # Start broker in new window
            broker_cmd = f'''
            Start-Process powershell -ArgumentList "-NoExit", "-Command", `
            "& 'C:\\Program Files\\mosquitto\\mosquitto.exe' -c {os.path.abspath(config_path)} -v"
            '''
            
            subprocess.run(["powershell", "-Command", broker_cmd])
            time.sleep(2)  # Wait for startup
            print("Mosquitto MQTT broker started")
            
        except Exception as e:
            print(f"Error starting broker: {e}")
            raise

    def on_connect(self, client, userdata, flags, rc):
            print("Connected to MQTT broker")
            # Core channels
            self.client.subscribe("game/server")
            self.client.subscribe("game/health")
            self.client.subscribe("game/wheel/response")
            self.client.subscribe("game/console")
            # Game channels
            self.client.subscribe("game/picker/response")
            self.client.subscribe("game/guesser/response")
            self.client.subscribe("game/better/response")
            self.client.subscribe("game/roles/#")  # All role assignments
            self.client.subscribe("game/client/#")  # All client messages
            print("Subscribed to all game channels")
        
    def on_message(self, client, userdata, msg):
        try:
            # Decode payload
            if isinstance(msg.payload, bytes):
                decoded = msg.payload.decode()
            else:
                decoded = msg.payload
                
            # Parse JSON - handle both string and dict formats
            if isinstance(decoded, str):
                try:
                    payload = json.loads(decoded)
                except:
                    payload = decoded
            else:
                payload = decoded
                
            topic = msg.topic
            
            # Extract message components
            if isinstance(payload, dict):
                msg_type = payload.get('type')
                data = payload.get('data')
                client_id = payload.get('id')
            else:
                print(f"Unexpected payload format: {payload}")
                return

            if msg_type == "connect":
                print(f"Client {client_id} connected")
                self.state.clients[client_id] = True
                if client_id == 0:
                    self.state.console_connected = True
                self.game.gui.update_gui()
            elif msg_type == "disconnect":
                print(f"Client {client_id} disconnected")
                # Remove from clients dictionary
                if client_id in self.state.clients:
                    self.state.clients.pop(client_id)
                # Remove from players list
                if hasattr(self.game, 'players'):
                    self.game.players = [p for p in self.game.players if p.id != client_id]
                    self.state.players = self.game.players
                # Update console status
                if client_id == 0:
                    self.state.console_connected = False
                # Update GUI
                self.game.gui.update_gui()

            if topic == "game/wheel/response":
                if msg_type == "light_wheel" and data == "done":
                    self.wheel_done = True
                    self.wheel_response_received.set()
                    
            elif topic == "game/picker/response":
                if msg_type == "pick" and self.wait_for_picker:
                    self.picker_number = int(data)
                    self.picker_response.set()
                    
            elif topic == "game/guesser/response":
                index = payload.get('index')
                if msg_type == "guess" and 0 <= int(data) <= 100:
                    self.guesser_numbers[index-1] = int(data)
                    self.guesser_responses[index-1].set()
                    
            elif topic == "game/better/response":
                if msg_type == "bet" and client_id in self.better_responses:
                    event, _ = self.better_responses[client_id]
                    self.better_responses[client_id] = (event, int(data))
                    event.set()
            elif topic == "game/console":
                if msg_type == "start":
                    self.state.started = True
                    self.state.accepting_players = False

            if msg_type == "ping":
                self.last_pings[client_id] = time.monotonic()
                    
        except Exception as e:
            print(f"Message handling error: {e}")

    def cleanup_loop(self):
        while self.cleanup_running:
            current_time = time.monotonic()
            # Check for clients that haven't pinged in 15 seconds
            for client_id in list(self.state.clients.keys()):
                if client_id == 0:  # Skip console
                    continue
                if current_time - self.last_pings.get(client_id, 0) > 15:
                    print(f"Client {client_id} timed out")
                    if client_id in self.state.clients:
                        self.state.clients.pop(client_id)
                    if hasattr(self.game, 'players'):
                        self.game.players = [p for p in self.game.players if p.id != client_id]
                        self.state.players = self.game.players
                    self.game.gui.update_gui()
            time.sleep(4)

    def __del__(self):
        self.cleanup_running = False

    def handle_game_command(self, client_id, command, data):
        try:
            if command == "pick":
                self.picker_number = int(data)
                self.picker_response.set()
            elif command == "guess":
                index = int(data.split('+')[0])  # Get index from guess+index format
                number = int(data.split(':')[1])
                self.guesser_numbers[index-1] = number
                self.guesser_responses[index-1].set()
            elif command == "bet":
                if client_id in self.better_responses:
                    event, _ = self.better_responses[client_id]
                    self.better_responses[client_id] = (event, int(data))
                    event.set()
        except Exception as e:
            print(f"Game command error: {e}")

    def wait_for_wheel_done(self, timeout=5):
        self.wheel_response_received.clear()
        self.wheel_done = False
        if self.wheel_response_received.wait(timeout):
            return self.wheel_done
        return False
    
    def wait_for_picker(self, timeout=300):
        return self.picker_response.wait(timeout)
        
    def wait_for_guessers(self, timeout=300):
        return all(event.wait(timeout) for event in self.guesser_responses)
        
    def wait_for_betters(self, timeout=300):
        return all(event.wait(timeout) for event, _ in self.better_responses.values())
            

    # filepath: /d:/projects/pycharm/GuessRoulette/game/server/main.py
    # ...existing code...
    def send(self, client_id, message):
        try:
            msg_json = json.loads(message)
            payload = {
                "type": msg_json.get("type", "unknown"),
                "data": msg_json.get("data", None),  # Fallback if 'data' missing
            }
            # If there's a "health" field, include it
            if "health" in msg_json:
                payload["health"] = msg_json["health"]

            topic = f"game/client/{client_id}"
            self.client.publish(topic, json.dumps(payload), qos=1)
        except json.JSONDecodeError as e:
            print(f"Error parsing message: {e}")
    # ...existing code...

    def broadcast(self, message):
        msg_parts = message.split(':').strip("{}").strip('"').split(',')
        payload = {
            "type": msg_parts[1],
            "data": msg_parts[4] if len(msg_parts) > 2 else None
        }
        topic = "game/broadcast"
        self.client.publish(topic, json.dumps(payload), qos=1)

    def handle_game_command(self, client_id, command, data):
        if command == "pick":
            self.handle_pick(client_id, data)
        elif command == "guess":
            self.handle_guess(client_id, data)
        elif command == "bet":
            self.handle_bet(client_id, data)

    def assign_role(self, client_id, role, index=None):
        payload = {
            "type": "role",
            "role": role,
            "index": index
        }
        self.client.publish(f"game/roles/{client_id}", 
                               json.dumps(payload), qos=1)
                               


class Game:
    def __init__(self):
        # Core components
        self.state = GameState()
        self.wifi = WiFiHotspot()
        setup_wifi_peers_registry()
        self.wifi.start_hotspot()
        self.server = GameServer(self, self.state)
        self.gui = GUI(self.state, self.wifi, self.server)

        # Game state
        self.round = 0
        self.max_rounds = self.state.max_rounds
        self.running = True
        
        # Player tracking
        self.players = []
        self.players_c = []  # Current round players
        self.picker = None
        self.guessers = []
        self.betters = []
        
        # Round state
        self.picker_num = None
        self.guesser_nums = [None, None]
        self.waiting_states = {
            'picker': False,
            'guessers': [False, False],
            'betters': []
        }
        
        # Start game threads
        threading.Thread(target=self.run).start()
        self.gui.root.mainloop()

    def run(self):
        update_timer = time.monotonic()
        while self.running:
            # Update GUI every second
            if time.monotonic() - update_timer > 1:
                self.gui.update_gui()
                update_timer = time.monotonic()

            # Handle player count changes
            if len(self.state.clients) != len(self.players):
                self.update_players()

            # Main game loop
            if self.state.started and not self.state.accepting_players:
                if len(self.players) < 3:
                    self.handle_not_enough_players()
                else:
                    self.game_loop()

            time.sleep(0.01)

    def handle_not_enough_players(self):
        print("Not enough players to start game")
        self.state.started = False
        self.state.accepting_players = True

    def game_loop(self):
        print(f"Starting round {self.round}")
        # Check win conditions
        if self.check_win_conditions():
            return

        # Start new round if no waiting states
        if not any(self.waiting_states.values()):
            self.start_new_round()
            return

        # Handle picker phase
        if self.waiting_states['picker']:
            if self.server.wait_for_picker(timeout=300):
                self.handle_picker_response()

        # Handle guessers and betters phase
        if any(self.waiting_states['guessers']) or any(self.waiting_states['betters']):
            if self.server.wait_for_guessers(timeout=300) and self.server.wait_for_betters(timeout=300):
                self.finalize_round()

    def start_new_round(self):
        self.round += 1
        self.players_c = [p for p in self.players if p.state != PlayerState.DEAD]
        
        # Select roles
        if self.select_roles():
            # Light wheel for picker
            self.server.send(0, json.dumps({
                "type": "light_wheel", 
                "data": self.picker.id
            }))
            
            if self.server.wait_for_wheel_done():
                # Assign roles
                self.assign_roles()
                self.waiting_states['picker'] = True
                self.waiting_states['guessers'] = [False, False]
                self.waiting_states['betters'] = [False] * len(self.betters)

    def select_roles(self):
        if len(self.players_c) < 3:
            return False
            
        # Select picker
        self.picker = random.choice(self.players_c)
        self.players_c.remove(self.picker)
        self.picker.state = PlayerState.PICKER
        
        # Select guessers
        self.guessers = random.sample(self.players_c, 2)
        for guesser in self.guessers:
            self.players_c.remove(guesser)
            guesser.state = PlayerState.GUESSER
            
        # Remaining players become betters
        self.betters = self.players_c
        for better in self.betters:
            better.state = PlayerState.BETTER
            
        return True
    
    def assign_roles(self):
        # Assign picker
        self.server.send(self.picker.id, json.dumps({
            "type": "role",
            "data": f"{PlayerState.PICKER}"
        }))
        
        # Assign betters with index
        for i, better in enumerate(self.betters):
            self.server.send(better.id, json.dumps({
                "type": "role",
                "data": f"{PlayerState.BETTER}+{i+1}"
            }))

    def handle_picker_response(self):
        self.picker_num = self.server.picker_number
        self.waiting_states['picker'] = False
        
        # Turn off wheel and prepare for guessers
        self.server.send(0, json.dumps({
            "type": "light_wheel",
            "data": "off"
        }))
        
        # Light wheel for guessers
        self.server.send(0, json.dumps({
            "type": "light_wheel",
            "data": [g.id for g in self.guessers]
        }))
        
        if self.server.wait_for_wheel_done():
            # Assign guesser roles
            for i, guesser in enumerate(self.guessers):
                self.server.send(guesser.id, json.dumps({
                    "type": "role",
                    "data": f"{PlayerState.GUESSER}+{i+1}"
                }))
            self.waiting_states['guessers'] = [True, True]
            self.waiting_states['betters'] = [True] * len(self.betters)

    def finalize_round(self):
        self.server.send(0, json.dumps({
            "type": "light_wheel",
            "data": "off"
        }))
        
        self.calculate_scores()
        self.reset_round()

    def calculate_scores(self):
        # Calculate differences
        guesser_diffs = [abs(self.picker_num - n) for n in self.guesser_nums]
        
        # Update guesser health
        if all(diff == 0 for diff in guesser_diffs):
            for guesser in self.guessers:
                guesser.health = 100 if not LIMITED else 15
        else:
            for i, (guesser, diff) in enumerate(zip(self.guessers, guesser_diffs)):
                if diff > guesser_diffs[1-i]:
                    guesser.health -= diff
                
        # Update better health
        for better in self.betters:
            diff = abs(better.bet - self.picker_num)
            if diff <= 10 if not LIMITED else 2:
                better.health += 10 if not LIMITED else 2
            elif diff == 0:
                better.health += self.picker_num
            elif diff <= 70 if not LIMITED else 10:
                better.health -= diff
                
        # Send health updates and check for deaths
        for player in self.players:
            self.server.send(player.id, json.dumps({
                "type": "health",
                "health": player.health
            }))
            
            if player.health <= 0:
                player.state = PlayerState.DEAD
                self.server.send(player.id, json.dumps({
                    "type": "role",
                    "data": f"{PlayerState.DEAD}"
                }))

    def reset_round(self):
        # Reset states
        self.picker = None
        self.guessers = []
        self.betters = []
        self.picker_num = None
        self.guesser_nums = [None, None]
        self.waiting_states = {
            'picker': False,
            'guessers': [False, False],
            'betters': []
        }

    def check_win_conditions(self):
        alive_players = [p for p in self.players if p.state != PlayerState.DEAD]
        
        if len(alive_players) < 3 or self.round >= self.max_rounds:
            winner = max(alive_players, key=lambda p: p.health)
            self.server.send(winner.id, json.dumps({"type": "win"}))
            time.sleep(15)
            
            for player in self.players:
                self.server.send(player.id, json.dumps({"type": "off"}))
                
            self.running = False
            return True
            
        return False
    
    def update_players(self):
        self.players = [Player(id) for id in self.state.clients.keys()]
        self.state.players = self.players


if __name__ == "__main__":
    game = Game()
    game.run()
