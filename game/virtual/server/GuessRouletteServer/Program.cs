using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Net;
using System.Threading;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.DependencyInjection;
using System.Runtime.InteropServices;
using System.Security.Principal;
using Microsoft.Win32;
using System.Windows;
using System.Text;


public enum PlayerRole
{
    DEFAULT,
    PICKER,
    GUESSER,
    BETTER,
    DEAD,
    WINNER
}

// Basic player
public class Player
{
    public Guid Id { get; set; } = Guid.NewGuid();
    public string Name { get; set; } = "";
    public PlayerRole Role { get; set; } = PlayerRole.DEFAULT;
    public int Health { get; set; } = 100;
    public bool HasSubmitted { get; set; } = false;
    public int SubmittedNumber { get; set; } = -1;

    public DateTime LastHeartbeat { get; set; } = DateTime.UtcNow;

    public bool IsAdmin { get; set; } = false; // Added property
}

// Holds game state
public class GameState
{
    private readonly object _lock = new object();
    public Dictionary<Guid, Player> Players = new Dictionary<Guid, Player>();
    public bool GameStarted = false;
    public int Round = 1;
    public int MaxRounds = 5; // example
    public bool SetupInProgress = false; // used to block next role assignment until previous submissions are done

    public bool IsShuttingDown = false; // New flag

    public event Action<Player> OnPlayerKicked;

    // In a real system, you might store these pick/guess/bet values differently
    // For demonstration, we store them in each player's SubmittedNumber

    public void KickPlayer(Guid playerId)
    {
        lock (_lock)
        {
            if (Players.ContainsKey(playerId))
            {
                var player = Players[playerId];
                Players.Remove(playerId);
                OnPlayerKicked?.Invoke(player);
                Console.WriteLine($"Player kicked: {player.Name}");
            }
        }
    }
}

public class RegistryHelper
{
    private const string RegPath = @"SYSTEM\CurrentControlSet\Services\icssvc\Settings";
    private const string KeyName = "WifiMaxPeers";
    private const int DefaultValue = 20;

    public static void SetupWifiPeers()
    {
        try
        {
            using var key = Registry.LocalMachine.OpenSubKey(RegPath, true);
            if (key == null)
            {
                using var newKey = Registry.LocalMachine.CreateSubKey(RegPath);
                newKey.SetValue(KeyName, DefaultValue, RegistryValueKind.DWord);
                ShowRestartPrompt();
                return;
            }

            var currentValue = key.GetValue(KeyName);
            if (currentValue == null || (int)currentValue < DefaultValue)
            {
                key.SetValue(KeyName, DefaultValue, RegistryValueKind.DWord);
                ShowRestartPrompt();
            }
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Failed to modify registry: {ex.Message}", 
                "Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private static void ShowRestartPrompt()
    {
        if (MessageBox.Show(
            "A registry key changing the number of devices that can connect to your PC's hotspot " +
            "has been created or edited. You will need to restart your computer to be able to effectively use this program. Would you like to restart your computer now?",
            "Restart Required",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning) == MessageBoxResult.Yes)
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = "shutdown.exe",
                Arguments = "/r /t 0",
                CreateNoWindow = true,
                UseShellExecute = false
            });
        }
    }
}

public static class AdminHelper
{
    [DllImport("shell32.dll")]
    private static extern int ShellExecuteW(IntPtr hwnd, string lpOperation, string lpFile, 
        string lpParameters, string lpDirectory, int nShowCmd);

    public static bool IsAdmin()
    {
        using (WindowsIdentity identity = WindowsIdentity.GetCurrent())
        {
            WindowsPrincipal principal = new WindowsPrincipal(identity);
            return principal.IsInRole(WindowsBuiltInRole.Administrator);
        }
    }

    public static void RestartAsAdmin()
    {
        if (!IsAdmin())
        {
            try
            {
                Console.WriteLine("Requesting admin privileges...");
                ProcessStartInfo startInfo = new ProcessStartInfo
                {
                    UseShellExecute = true,
                    Verb = "runas",
                    FileName = Process.GetCurrentProcess().MainModule?.FileName ?? "",
                    Arguments = string.Join(" ", Environment.GetCommandLineArgs().Skip(1)
                        .Select(arg => $"\"{arg}\"")),
                    WorkingDirectory = Environment.CurrentDirectory
                };

                Process.Start(startInfo);
                Environment.Exit(0);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Failed to restart with admin rights: {ex.Message}");
                Environment.Exit(1);
            }
        }
    }
}

// Manages Windows hotspot via netsh (simplified example)
public class WiFiHotspot
{
    public string oldSSID = "";
    public string oldPassword = "";
    public string originalBand = "";

    private bool TestNetwork()
    {
        string psCommand = @"
            $network = Get-NetAdapter | Where-Object {$_.Name -like '*Local*'} | Select-Object Status
            Write-Host $network.Status";

        ProcessStartInfo startInfo = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = $"-Command {psCommand}",
            RedirectStandardOutput = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };

        using (Process process = Process.Start(startInfo))
        {
            string output = process.StandardOutput.ReadToEnd();
            process.WaitForExit();

            if (!output.Contains("Up"))
            {
                Console.WriteLine("✗ Network is not active");
                return false;
            }
            Console.WriteLine("✓ Network is active");
            return true;
        }
    }

    private void GetOriginalSettings()
    {
        string psCommand = @"
            Add-Type -AssemblyName System.Runtime.WindowsRuntime
            $TetheringManager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]
            $connectionProfile = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
            $manager = $TetheringManager::CreateFromConnectionProfile($connectionProfile)
            $config = $manager.GetCurrentAccessPointConfiguration()
            Write-Host ""SSID:$($config.Ssid)""
            Write-Host ""KEY:$($config.Passphrase)""
            Write-Host ""BAND:$($config.Band)""";

        using (Process process = Process.Start(new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = $"-Command {psCommand}",
            RedirectStandardOutput = true,
            UseShellExecute = false,
            CreateNoWindow = true
        }))
        {
            var lines = process.StandardOutput.ReadToEnd().Split('\n');
            process.WaitForExit();

            this.oldSSID = lines.FirstOrDefault(l => l.Contains("SSID:"))?.Split(':')[1].Trim() ?? "";
            this.oldPassword = lines.FirstOrDefault(l => l.Contains("KEY:"))?.Split(':')[1].Trim() ?? "";
            this.originalBand = lines.FirstOrDefault(l => l.Contains("BAND:"))?.Split(':')[1].Trim() ?? "TwoPointFourGigahertz";

            Console.WriteLine($"Found settings - SSID: {oldSSID}, Password: {oldPassword}, Band: {originalBand}");
        }
    }

    public bool StartHotspot(string ssid = "GuessRoulette", string password = "password123")
    {
        try
        {
            GetOriginalSettings();
            string script = $@"
            $ErrorActionPreference = 'SilentlyContinue'
            Add-Type -AssemblyName System.Runtime.WindowsRuntime

            $connectionProfile = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
            if ($null -eq $connectionProfile) {{
                Write-Error 'No active network connection found'
                exit 1
            }}

            $TetheringManager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]
            $manager = $TetheringManager::CreateFromConnectionProfile($connectionProfile)
            if ($null -eq $manager) {{
                Write-Error 'Failed to create tethering manager'
                exit 1
            }}

            $config = $manager.GetCurrentAccessPointConfiguration()
            $config.Ssid = '{ssid}'
            $config.Passphrase = '{password}'
            $config.Band = [Windows.Networking.NetworkOperators.TetheringWiFiBand]::TwoPointFourGigahertz
            $null = $manager.ConfigureAccessPointAsync($config).AsTask().Wait()
            $null = $manager.StartTetheringAsync().AsTask().Wait()

            Write-Host 'Hotspot started'
            $ErrorActionPreference = 'Continue'
            ";
            RunPowershellScript(script);
            Console.WriteLine($"Hotspot started: SSID={ssid}, PASSWORD={password}");
            return true;
        }
        catch (Exception ex)
        {
            Console.WriteLine("Failed to start hotspot: " + ex.Message);
            return false;
        }
    }

    private void RunPowershellScript(string script)
    {
        using (var process = new System.Diagnostics.Process())
        {
            var psi = new System.Diagnostics.ProcessStartInfo
            {
                FileName = "powershell.exe",
                Arguments = $"-Command \"{script}\"",
                CreateNoWindow = true,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };

            process.StartInfo = psi;
            process.Start();
            string output = process.StandardOutput.ReadToEnd();
            string error = process.StandardError.ReadToEnd();
            process.WaitForExit();

            if (process.ExitCode != 0)
            {
                throw new Exception($"Powershell command failed.\nOutput: {output}\nError: {error}");
            }
        }
    }

    public bool StopHotspot()
    {
        try
        {
            Console.WriteLine($"Original SSID: {this.oldSSID}");
            Console.WriteLine($"Original Password: {this.oldPassword}");
            Console.WriteLine($"Original Band: {this.originalBand}");

            string psCommand = $@"
                Add-Type -AssemblyName System.Runtime.WindowsRuntime
                
                $connectionProfile = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
                $TetheringManager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]
                $manager = $TetheringManager::CreateFromConnectionProfile($connectionProfile)
                
                # Stop tethering first
                $null = $manager.StopTetheringAsync()
                Write-Host 'Tethering stopped'
                
                $ssid = '{this.oldSSID}'
                $pass = '{this.oldPassword}'
                $band = '{this.originalBand}'
                
                Write-Host ""Debug - SSID: $ssid""
                Write-Host ""Debug - Pass: $pass""
                Write-Host ""Debug - Band: $band""
                
                if ($ssid -ne '' -and $pass -ne '') {{
                    $config = $manager.GetCurrentAccessPointConfiguration()
                    $config.Ssid = $ssid
                    $config.Passphrase = $pass
                    $config.Band = [Windows.Networking.NetworkOperators.TetheringWiFiBand]::$band
                    $null = $manager.ConfigureAccessPointAsync($config)
                    Write-Host 'Reset to original settings'
                }} else {{
                    Write-Host 'No original settings to restore'
                }}";

            Console.WriteLine("Stopping Mobile Hotspot...");

            var startInfo = new ProcessStartInfo
            {
                FileName = "powershell.exe",
                Arguments = $"-Command {psCommand}",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };

            using (var process = Process.Start(startInfo))
            {
                string output = process.StandardOutput.ReadToEnd();
                string error = process.StandardError.ReadToEnd();
                process.WaitForExit();

                Console.WriteLine($"Stop output: {output}");
                if (!string.IsNullOrEmpty(error))
                {
                    Console.WriteLine($"Stop errors: {error}");
                }
            }

            TestNetwork();
            return true;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"✗ Stop hotspot error: {ex.Message}");
            return false;
        }
    }
}

public class GameLogic
{
    private readonly GameState _state;
    private readonly object _lockObject = new object();

    public GameLogic(GameState state)
    {
        _state = state;
    }

    // Called to start or continue the game
    public void StartGame()
    {
        lock (_lockObject)
        {
            if (_state.GameStarted) return;
            Console.WriteLine("Game started.");
            _state.GameStarted = true;
        }
    }

    // Main logic to assign roles, handle submissions, and run rounds
    // This is called at various stages: after a submission, or at the start of a new round, etc.
    public void ProceedGameFlow()
    {
        lock (_lockObject)
        {
            if (!_state.GameStarted || _state.SetupInProgress) return;

            _state.SetupInProgress = true;

            // If we have fewer than 3 alive players, we can still proceed, but roles might be limited
            var alivePlayers = _state.Players.Values
                .Where(p => p.Role != PlayerRole.DEAD && p.Health > 0)
                .ToList();

            // If no alive players or only 1 or 2 left, handle potential end conditions
            if (alivePlayers.Count <= 1)
            {
                // Single or zero survivors => immediate winner or no one
                if (alivePlayers.Count == 1)
                {
                    alivePlayers[0].Role = PlayerRole.WINNER;
                    Console.WriteLine($"Winner: {alivePlayers[0].Name}");
                }
                EndGame();
                _state.SetupInProgress = false;
                return;
            }
            if (alivePlayers.Count == 2)
            {
                // Compare health
                var ordered = alivePlayers.OrderByDescending(a => a.Health).ToList();
                if (ordered[0].Health != ordered[1].Health)
                {
                    ordered[0].Role = PlayerRole.WINNER;
                    Console.WriteLine($"Winner: {ordered[0].Name}");
                    EndGame();
                    _state.SetupInProgress = false;
                    return;
                }
                // If a tie, we can keep going or do a tie-break logic. For simplicity, we keep going.
            }

            // If we've exceeded max rounds, pick the top health
            if (_state.Round > _state.MaxRounds)
            {
                var best = alivePlayers.OrderByDescending(a => a.Health).FirstOrDefault();
                if (best != null)
                {
                    best.Role = PlayerRole.WINNER;
                    Console.WriteLine($"Winner by round limit: {best.Name}");
                }
                EndGame();
                _state.SetupInProgress = false;
                return;
            }

            // Otherwise, proceed with normal round flow:
            // 1) Clear roles from last round, except dead or winner
            foreach (var p in alivePlayers)
            {
                if (p.Role != PlayerRole.WINNER && p.Role != PlayerRole.DEAD)
                    p.Role = PlayerRole.DEFAULT;
                p.HasSubmitted = false;
                p.SubmittedNumber = -1;
            }

            // 2) Assign 1 picker, 2 guessers if possible, rest betters
            // Very naive approach
            var shuffle = alivePlayers.OrderBy(_ => Guid.NewGuid()).ToList();
            if (shuffle.Count > 0) shuffle[0].Role = PlayerRole.PICKER;
            if (shuffle.Count > 1) shuffle[1].Role = PlayerRole.GUESSER;
            if (shuffle.Count > 2) shuffle[2].Role = PlayerRole.GUESSER;

            // The rest become betters
            for (int i = 3; i < shuffle.Count; i++)
            {
                shuffle[i].Role = PlayerRole.BETTER;
            }

            // Now we wait for submissions from players. We'll move on only after:
            // - The picker has submitted
            // - All guessers and betters have submitted
            // The actual waiting is triggered by the site interactions in this sample.
            // We'll do a simple check in EvaluateSubmissions whenever players finish.
            Console.WriteLine($"Round {_state.Round} roles assigned.");

            _state.SetupInProgress = false;
        }
    }

    // Evaluate when a user just submitted
    public void EvaluateSubmissions()
    {
        lock (_lockObject)
        {
            if (!_state.GameStarted) return;

            // Are we in the "picker" stage? The next step is guessers + betters
            // 1) Check if the PICKER is done
            var picker = _state.Players.Values
                .FirstOrDefault(p => p.Role == PlayerRole.PICKER && p.Health > 0);
            if (picker != null && !picker.HasSubmitted)
            {
                // The game is waiting for the picker
                return;
            }
            // If the picker is assigned and has submitted, now guessers + betters
            // Are guessers + betters done?
            var guessersOrBetters = _state.Players.Values
                .Where(p => (p.Role == PlayerRole.GUESSER || p.Role == PlayerRole.BETTER) && p.Health > 0)
                .ToList();

            // If none exist, skip
            if (guessersOrBetters.Count > 0 && guessersOrBetters.Any(g => !g.HasSubmitted))
            {
                // Some guessers/betters haven't submitted
                return;
            }

            // If we reach here, everyone who needed to submit has submitted
            // 2) Calculate new health or apply game logic
            CalculateHealthAndReset();

            // 3) Advance round or declare winner
            _state.Round++;
            ProceedGameFlow(); // this also checks if we exceeded max rounds
        }
    }

    // A placeholder example: subtract health from guessers/betters randomly
    // or use the picker's number to do something
    private void CalculateHealthAndReset()
    {
        var picker = _state.Players.Values.FirstOrDefault(p => p.Role == PlayerRole.PICKER && p.Health > 0);
        int selectedNumber = picker?.SubmittedNumber ?? 0;

        // For guessers and betters, a naive logic: each guesser/better differs from selected
        // reduce health by difference for guessers, or by some fixed amount for betters
        var guessers = _state.Players.Values.Where(p => p.Role == PlayerRole.GUESSER && p.Health > 0);
        foreach (var g in guessers)
        {
            int diff = Math.Abs(g.SubmittedNumber - selectedNumber);
            g.Health -= diff; 
            if (g.Health <= 0)
            {
                g.Health = 0;
                g.Role = PlayerRole.DEAD;
                Console.WriteLine($"{g.Name} has died.");
            }
        }

        var betters = _state.Players.Values.Where(p => p.Role == PlayerRole.BETTER && p.Health > 0);
        foreach (var b in betters)
        {
            int diff = Math.Abs(b.SubmittedNumber - selectedNumber);
            // Arbitrary logic: smaller difference => some reward or lesser penalty
            b.Health -= (diff / 2);
            if (b.Health <= 0)
            {
                b.Health = 0;
                b.Role = PlayerRole.DEAD;
                Console.WriteLine($"{b.Name} has died.");
            }
        }

        // The "game reset" part: we do NOT restore any roles, we only keep them if they're dead or winner
        // We'll handle official role resets in "ProceedGameFlow()" for the next round
        Console.WriteLine("Round complete, updated health. Returning everyone to base page...");
    }

    private void EndGame()
    {
        // Mark the game as ended. Realistically you'd do a final page for all players, etc.
        _state.GameStarted = false;
        Console.WriteLine("Game ended.");
    }
}

public class Program
{
    private static WiFiHotspot hotspot;
    private static bool cleanupDone = false;


    private static void Cleanup(GameState gs)
    {
        // set local gameState variable erual to gs
        var gameState = gs;
        if (cleanupDone) return;
        cleanupDone = true;
        
        Console.WriteLine("Performing cleanup...");
        if (gameState != null)
        {
            gameState.IsShuttingDown = true; // Set shutdown flag
        }
        Thread.Sleep(1000); // Wait for any pending requests to finish
        hotspot?.StopHotspot();
        // sleep for 5 sec to allow for error messages to be viewed
        Thread.Sleep(4000);
    }

    private static void SetupCleanupHandlers(GameState gs)
    {
        // Handle Ctrl+C and other console events
        Console.CancelKeyPress += (s, e) =>
        {
            e.Cancel = true;
            Cleanup(gs);
            Environment.Exit(0);
        };

        // Handle process termination
        AppDomain.CurrentDomain.ProcessExit += (s, e) =>
        {
            Cleanup(gs);
        };
    }
    public static void Main(string[] args)
    {
        try 
        {
            if (!AdminHelper.IsAdmin())
            {
                AdminHelper.RestartAsAdmin();
                return; // Exit non-elevated instance
            }

            RegistryHelper.SetupWifiPeers();

            hotspot = new WiFiHotspot();

            // Start hotspot
            if (!hotspot.StartHotspot())
            {
                throw new Exception("Failed to start hotspot");
            }

            var builder = WebApplication.CreateBuilder(args);

            // Initialize game state and logic
            var gameState = new GameState();
            var gameLogic = new GameLogic(gameState);

            // Initialize admin player
            var adminPlayer = new Player { Name = "server", IsAdmin = true };
            gameState.Players[adminPlayer.Id] = adminPlayer;
            Console.WriteLine($"Admin registered: {adminPlayer.Name}, id={adminPlayer.Id}");

            SetupCleanupHandlers(gameState);

            builder.Services.AddSingleton(gameState);
            builder.Services.AddSingleton(gameLogic);

            var app = builder.Build();

            // Middleware to serve static files if needed
            Task.Run(async () =>
            {
                while (true)
                {
                    Thread.Sleep(3000); // Check every 30 seconds
                    var inactivePlayers = gameState.Players
                        .Where(p => !gameState.GameStarted && (DateTime.UtcNow - p.Value.LastHeartbeat).TotalSeconds > 60)
                        .Select(p => p.Key)
                        .ToList();

                    foreach (var playerId in inactivePlayers)
                    {
                        gameState.KickPlayer(playerId);
                    }
                }
            });

            // 1) GET "/" => If no ?id=, show name form. Otherwise, show the player's main page
            app.MapGet("/", (HttpRequest request, GameState gs) =>
            {
                // get 'id' from query
                var idStr = request.Query["id"].ToString();
                if (string.IsNullOrWhiteSpace(idStr))
                {
                    // No ID => show name input page
                    return Results.Content(GenerateNameFormHtml(), "text/html");
                }
                else
                {
                    // Has ID => parse, find the player
                    if (!Guid.TryParse(idStr, out Guid playerId)) 
                    {
                        // Invalid => show name form
                        return Results.Content(GenerateNameFormHtml("Invalid ID, please register again."), "text/html");
                    }

                    if (!gs.Players.ContainsKey(playerId))
                    {
                        return Results.Content(GenerateNameFormHtml("Unknown ID, please register again."), "text/html");
                    }

                    // We have a known player => show the main game page
                    var p = gs.Players[playerId];
                    if (p.Name.ToLower() == "server")
                    {
                        // Admin dashboard
                        return Results.Content(GenerateAdminDashboardHtml(gs), "text/html");
                    }
                    else
                    {
                        // Regular player page
                        return Results.Content(GenerateGamePageHtml(p, gs), "text/html");
                    }
                }
            });

            // 2) POST "/register" => create a new player, add to dictionary, redirect to "/?id=..."
            app.MapPost("/register", async (HttpRequest request, GameState gs) =>
            {
                var form = await request.ReadFormAsync();
                var name = form["playerName"].ToString().Trim();
                if (string.IsNullOrEmpty(name))
                {
                    return Results.Content(GenerateNameFormHtml("Please enter a valid name."), "text/html");
                }

                var newPlayer = new Player { Name = name };
                gs.Players[newPlayer.Id] = newPlayer;
                Console.WriteLine($"Player registered: {name}, id={newPlayer.Id}");
                // redirect to main page
                return Results.Redirect($"/?id={newPlayer.Id}");
            });

            // 3) POST "/submitNumber" => store the user input number, mark HasSubmitted = true, evaluate submissions
            app.MapPost("/submitNumber", async (HttpRequest request, GameState gs, GameLogic logic) =>
            {
                var form = await request.ReadFormAsync();
                var idStr = form["playerId"].ToString();
                var inputStr = form["number"].ToString();
                if (!Guid.TryParse(idStr, out Guid playerId) || !gs.Players.ContainsKey(playerId))
                {
                    return Results.Content("<h1>Invalid player ID</h1>", "text/html");
                }
                if (!int.TryParse(inputStr, out int submittedNumber))
                {
                    // If invalid, use -1
                    submittedNumber = -1;
                }

                var player = gs.Players[playerId];
                player.SubmittedNumber = submittedNumber;
                player.HasSubmitted = true;
                Console.WriteLine($"{player.Name} submitted {submittedNumber}");

                // Evaluate the game
                logic.EvaluateSubmissions();

                // Redirect back
                return Results.Redirect($"/?id={playerId}");
            });

            // 4) POST "/admin/startGame" => starts the game and sets initial roles
            // Example for /admin/startGame
            app.MapPost("/admin/startGame", (HttpRequest request, GameState gs, GameLogic logic) =>
            {
                if (!IsAdminRequest(request, gs))
                {
                    return Results.Json(new { message = "Forbidden." }, statusCode: 403);
                }

                if (gs.GameStarted)
                {
                    return Results.Json(new { message = "Game is already running." });
                }

                logic.StartGame();
                logic.ProceedGameFlow();
                Console.WriteLine("Admin started the game.");
                return Results.Json(new { message = "Game started." });
});

            // Similarly update other admin endpoints to return JSON instead of redirects
            app.MapPost("/admin/incMaxRounds", (HttpRequest request, GameState gs) =>
            {
                if (!IsAdminRequest(request, gs))
                {
                    return Results.StatusCode(403);
                }

                gs.MaxRounds += 1;
                Console.WriteLine($"Admin incremented MaxRounds to {gs.MaxRounds}");
                return Results.Json(new { message = "Max rounds increased.", newMaxRounds = gs.MaxRounds });
            });

            app.MapPost("/admin/decMaxRounds", (HttpRequest request, GameState gs) =>
            {
                if (!IsAdminRequest(request, gs))
                {
                    return Results.StatusCode(403);
                }

                if (gs.MaxRounds > 1)
                {
                    gs.MaxRounds -= 1;
                    Console.WriteLine($"Admin decremented MaxRounds to {gs.MaxRounds}");
                }
                return Results.Json(new { message = "Max rounds decreased.", newMaxRounds = gs.MaxRounds });
            });

            // POST "/admin/kickPlayer" => Kicks a player
            app.MapPost("/admin/kickPlayer", async (HttpRequest request, GameState gs) =>
            {
                // Extract admin ID from headers
                if (!request.Headers.TryGetValue("Admin-Id", out var adminIdHeaders))
                {
                    return Results.Json(new { message = "Admin ID missing." }, statusCode: 400);
                }

                var adminIdStr = adminIdHeaders.FirstOrDefault();
                if (!Guid.TryParse(adminIdStr, out Guid adminId) || !gs.Players.ContainsKey(adminId))
                {
                    return Results.Json(new { message = "Invalid Admin ID." }, statusCode: 400);
                }

                var adminPlayer = gs.Players[adminId];
                if (!adminPlayer.IsAdmin)
                {
                    return Results.Json(new { message = "Unauthorized." }, statusCode: 403);
                }

                // Read the form data for playerId to kick
                var form = await request.ReadFormAsync();
                var playerIdStr = form["playerId"].ToString();
                if (Guid.TryParse(playerIdStr, out Guid playerId))
                {
                    if (gs.Players.ContainsKey(playerId))
                    {
                        var player = gs.Players[playerId];
                        if (player.IsAdmin)
                        {
                            return Results.Json(new { message = "Cannot kick admin player." }, statusCode: 400);
                        }

                        // Check if the player is already dead or kicked
                        if (player.Role == PlayerRole.DEAD)
                        {
                            return Results.Json(new { message = "Player is already dead." }, statusCode: 400);
                        }

                        gs.KickPlayer(playerId);
                        return Results.Json(new { message = "Player kicked successfully." });
                    }
                    else
                    {
                        return Results.Json(new { message = "Player ID not found." }, statusCode: 404);
                    }
                }

                return Results.Json(new { message = "Invalid Player ID." }, statusCode: 400);
            });

            app.MapPost("/heartbeat", async (HttpRequest request, GameState gs) =>
            {
                var form = await request.ReadFormAsync();
                var playerIdStr = form["playerId"].ToString();
                if (Guid.TryParse(playerIdStr, out Guid playerId) && gs.Players.ContainsKey(playerId))
                {
                    gs.Players[playerId].LastHeartbeat = DateTime.UtcNow;
                }
                return Results.Ok();
            });

            app.Run("http://0.0.0.0:8080");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Error: {ex.Message}");
            //Cleanup(gameState);
        }

        static bool IsAdminRequest(HttpRequest request, GameState gs)
        {
            // Extract 'id' from query
            var idStr = request.Query["id"].ToString();
            if (string.IsNullOrWhiteSpace(idStr))
                return false;

            if (!Guid.TryParse(idStr, out Guid playerId))
                return false;

            if (!gs.Players.ContainsKey(playerId))
                return false;

            var player = gs.Players[playerId];
            return player.Name.ToLower() == "server";
        }

        // HTML generator for name form
        static string GenerateNameFormHtml(string msg = "")
        {
            var message = string.IsNullOrWhiteSpace(msg) ? "" : $"<p style='color:red;'>{msg}</p>";
            return $@"
    <!DOCTYPE html>
    <html>
    <head>
        <meta name='viewport' content='width=device-width, initial-scale=1.0' />
        <title>Register</title>
    </head>
    <body>
        {message}
        <h1>Enter Your Name</h1>
        <form method='post' action='/register'>
            <input type='text' name='playerName' placeholder='Your Name' required />
            <button type='submit'>Submit</button>
        </form>
    </body>
    </html>
    ";
        }

        static string GenerateGamePageHtml(Player p, GameState gs)
        {
            if (gs.IsShuttingDown)
            {
                return @"
        <!DOCTYPE html>
        <html>
        <head><meta name='viewport' content='width=device-width, initial-scale=1.0' /></head>
        <body>
            <h1>Server Shutting Down...</h1>
        </body>
        </html>
        ";
            }
            if (p.Role == PlayerRole.WINNER)
            {
                return $@"
    <!DOCTYPE html>
    <html>
    <head><meta name='viewport' content='width=device-width, initial-scale=1.0' /></head>
    <body>
        <h1>Congratulations, {p.Name}! You have won!</h1>
    </body>
    </html>
    ";
            }
            if (p.Health <= 0 || p.Role == PlayerRole.DEAD)
            {
                return $@"
    <!DOCTYPE html>
    <html>
    <head><meta name='viewport' content='width=device-width, initial-scale=1.0' /></head>
    <body>
        <h2>Sorry {p.Name}, you are dead.</h2>
        <p>Health: {p.Health}</p>
    </body>
    </html>
    ";
            }

            // Default or waiting page
            // Show player's role, if they must input a number, show the form
            string roleDisplay = p.Role.ToString();
            string health = p.Health.ToString();
            string content = $"<p>Role: {roleDisplay}, Health: {health}</p>";

            // If the player is PICKER, GUESSER, or BETTER, let's give them a number form
            if (p.Role == PlayerRole.PICKER || p.Role == PlayerRole.GUESSER || p.Role == PlayerRole.BETTER)
            {
                // If they haven't submitted yet, show a form
                if (!p.HasSubmitted)
                {
                    content += $@"
    <form method='post' action='/submitNumber'>
        <input type='hidden' name='playerId' value='{p.Id}' />
        <label for='number'>Pick a number (0-100):</label>
        <input type='number' name='number' min='0' max='100' required />
        <button type='submit'>Submit</button>
    </form>
    ";
                }
                else
                {
                    content += "<p>Waiting for others to finish...</p>";
                }
            }
            else
            {
                // Default role or any other waiting role => just show health
                content += "<p>Waiting for next round...</p>";
            }

            string heartbeatScript = @"
                <script>
                    setInterval(() => {
                        fetch('/heartbeat', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                            body: `playerId=" + p.Id + @"`
                        });
                    }, 30000); // every 30 seconds
                </script>";

            return $@"
                <!DOCTYPE html>
                <html>
                <head><meta name='viewport' content='width=device-width, initial-scale=1.0' /></head>
                <body>
                    <h1>Welcome, {p.Name}</h1>
                    {content}
                    {heartbeatScript}
                </body>
                </html>
                ";
        }
    }

     // HTML generator for admin dashboard
    static string GenerateAdminDashboardHtml(GameState gs)
{
    StringBuilder playerListHtml = new StringBuilder();
    playerListHtml.Append("<h2>Player List</h2>");
    playerListHtml.Append("<table border='1' cellpadding='5' cellspacing='0'>");
    playerListHtml.Append("<tr><th>Name</th><th>Role</th><th>Health</th><th>Action</th></tr>");

    foreach (var player in gs.Players.Values)
    {
        if (player.IsAdmin) continue; // Exclude admin players
        playerListHtml.Append($@"
        <tr>
            <td>{player.Name}</td>
            <td>{player.Role}</td>
            <td>{player.Health}</td>
            <td>
                <button type='button' onclick='kickPlayer(""{player.Id}"")'>Kick</button>
            </td>
        </tr>");
    }

    playerListHtml.Append("</table>");

    // Retrieve admin's ID
    var adminPlayer = gs.Players.Values.FirstOrDefault(p => p.IsAdmin);
    string adminId = adminPlayer != null ? adminPlayer.Id.ToString() : "";

    // Admin controls: Start Game, Increment MaxRounds, Decrement MaxRounds
    string controls = $@"
    <h2>Admin Controls</h2>
    <button type='button' onclick='startGame()'>Start Game</button>
    <button type='button' onclick='increaseMaxRounds()'>Increase Max Rounds</button>
    <button type='button' onclick='decreaseMaxRounds()'>Decrease Max Rounds</button>
    <p>Current Max Rounds: <span id='maxRounds'>{gs.MaxRounds}</span></p>

    <script>
    function startGame() {{
        fetch('/admin/startGame', {{ method: 'POST' }})
            .then(response => response.json())
            .then(data => {{
                alert(data.message);
                location.reload();
            }})
            .catch(error => console.error('Error:', error));
    }}

    function increaseMaxRounds() {{
        fetch('/admin/incMaxRounds', {{ method: 'POST' }})
            .then(response => response.json())
            .then(data => {{
                alert(data.message);
                document.getElementById('maxRounds').innerText = data.newMaxRounds;
            }})
            .catch(error => console.error('Error:', error));
    }}

    function decreaseMaxRounds() {{
        fetch('/admin/decMaxRounds', {{ method: 'POST' }})
            .then(response => response.json())
            .then(data => {{
                alert(data.message);
                document.getElementById('maxRounds').innerText = data.newMaxRounds;
            }})
            .catch(error => console.error('Error:', error));
    }}

    function kickPlayer(playerId) {{
        if (confirm('Are you sure you want to kick this player?')) {{
            // Disable the button to prevent spamming
            event.target.disabled = true;

            fetch('/admin/kickPlayer', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Admin-Id': '{adminId}'
                }},
                body: `playerId=${{playerId}}`
            }})
            .then(response => response.json())
            .then(data => {{
                alert(data.message);
                location.reload();
            }})
            .catch(error => {{
                console.error('Error:', error);
                event.target.disabled = false; // Re-enable if there's an error
            }});
        }}
    }}

    // Auto-refresh the admin dashboard every 30 seconds
    setInterval(() => {{
        location.reload();
    }}, 3000);
    </script>
    ";

    return $@"
    <!DOCTYPE html>
    <html>
    <head>
        <meta name='viewport' content='width=device-width, initial-scale=1.0' />
        <title>Admin Dashboard</title>
    </head>
    <body>
        <h1>Admin Dashboard</h1>
        {playerListHtml}
        {controls}
    </body>
    </html>
    ";
}
}