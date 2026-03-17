# Carimans MCP Connectors - Auto-Updater
# Fetches the MCP registry from GitHub and syncs claude_desktop_config.json

$ErrorActionPreference = "Stop"

$RegistryUrl    = "https://raw.githubusercontent.com/ConstantFlowBlegium/carimans-mcp-connectors/main/registry/mcp-registry.json"
$SelfUrl        = "https://raw.githubusercontent.com/ConstantFlowBlegium/carimans-mcp-connectors/main/installer/updater.ps1"
$LogFile        = "$env:TEMP\carimans-mcp-connectors-updater.log"

# Detect Claude Desktop config path.
# Standard install: %APPDATA%\Claude\
# Windows Store / MSIX install: %LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\
$ConfigPath = "$env:APPDATA\Claude\claude_desktop_config.json"
if (-not (Test-Path "$env:APPDATA\Claude")) {
    $pkg = Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory -Filter "Claude_*" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pkg) {
        $ConfigPath = Join-Path $pkg.FullName "LocalCache\Roaming\Claude\claude_desktop_config.json"
    }
}

Add-Type -AssemblyName Microsoft.VisualBasic

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Show-TokenPrompt {
    param(
        [string]$ServerName,
        [string]$TokenEnvVar
    )
    $title = "New tool available in Claude Desktop"
    $message = @"
A new tool was added to Claude Desktop: $ServerName

To activate it on your computer:
  1. Open Bitwarden
  2. Search for: $TokenEnvVar
  3. Copy the token
  4. Paste it in the box below and click OK

Press Cancel to skip (you can run the setup again later to activate it).
"@
    $result = [Microsoft.VisualBasic.Interaction]::InputBox($message, $title, "")
    return $result
}

function Main {
    Write-Log "--- Carimans MCP Updater started ---"

    # 0a. Refresh PATH from registry so Node.js/npm is visible even in stale sessions
    # (e.g. when the installer runs right after Node.js was installed in the same boot)
    try {
        $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        $userPath    = [System.Environment]::GetEnvironmentVariable("Path", "User")
        $env:PATH    = (($machinePath + ";" + $userPath) -replace ';;+', ';').TrimEnd(';')
    }
    catch {
        Write-Log "WARNING: Could not refresh PATH from registry: $_"
    }

    # 0b. Self-update: fetch latest version from GitHub and replace local copy if changed.
    # The current run continues with this version; the new version is used on the next run.
    $selfPath = $MyInvocation.MyCommand.Path
    if ($selfPath -and (Test-Path $selfPath)) {
        try {
            $latest = (Invoke-WebRequest -Uri $SelfUrl -UseBasicParsing -TimeoutSec 10).Content
            $current = [System.IO.File]::ReadAllText($selfPath, (New-Object System.Text.UTF8Encoding $false))
            if ($latest.Trim() -ne $current.Trim()) {
                [System.IO.File]::WriteAllText($selfPath, $latest, (New-Object System.Text.UTF8Encoding $false))
                Write-Log "Updater self-updated from GitHub - new version will apply on next run"
            }
        }
        catch {
            Write-Log "WARNING: Could not self-update: $_"
        }
    }

    # 1. Ensure mcp-remote is globally installed (npx does not work reliably on Windows)
    Write-Log "Ensuring mcp-remote is installed globally..."
    try {
        # On a fresh Node.js install the npm global dir may not exist yet - create it first
        $npmGlobalDir = "$env:APPDATA\npm"
        if (-not (Test-Path $npmGlobalDir)) {
            New-Item -ItemType Directory -Path $npmGlobalDir -Force | Out-Null
            Write-Log "Created npm global directory: $npmGlobalDir"
        }
        $npmOutput = & npm list -g mcp-remote 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Installing mcp-remote globally..."
            & npm install -g mcp-remote 2>&1 | Out-Null
            Write-Log "mcp-remote installed"
        }
        else {
            Write-Log "mcp-remote already installed"
        }
    }
    catch {
        Write-Log "WARNING: Could not install mcp-remote: $_"
    }

    # 2. Resolve the full path to mcp-remote.cmd.
    # Must be .cmd - Claude Desktop (Electron) cannot execute .ps1 files directly.
    $mcpRemotePath = $null
    try {
        $npmPrefix = (& npm prefix -g 2>&1).Trim()
        $candidate = Join-Path $npmPrefix "mcp-remote.cmd"
        if (Test-Path $candidate) {
            $mcpRemotePath = $candidate
        }
    }
    catch {}
    if (-not $mcpRemotePath) {
        try {
            $resolved = (Get-Command "mcp-remote" -ErrorAction Stop).Source
            if ($resolved -like "*.cmd") {
                $mcpRemotePath = $resolved
            }
            else {
                $cmdSibling = [System.IO.Path]::ChangeExtension($resolved, ".cmd")
                if (Test-Path $cmdSibling) {
                    $mcpRemotePath = $cmdSibling
                }
                else {
                    $mcpRemotePath = $resolved
                }
            }
        }
        catch {
            Write-Log "WARNING: Could not resolve mcp-remote path - falling back to 'mcp-remote'"
            $mcpRemotePath = "mcp-remote"
        }
    }
    Write-Log "Resolved mcp-remote path: $mcpRemotePath"

    # If the path contains spaces, convert to 8.3 short path.
    # Claude Desktop spawns .cmd files as: cmd.exe /C <path> <args>
    # cmd.exe splits on spaces, so a path like "C:\Users\Vlodimyr Vahchuk\...\mcp-remote.cmd"
    # causes 'C:\Users\Vlodimyr' is not recognized errors.
    if ($mcpRemotePath -and ($mcpRemotePath -match ' ') -and (Test-Path $mcpRemotePath)) {
        try {
            $shortPath = (& cmd.exe /c "for %I in (`"$mcpRemotePath`") do @echo %~sI").Trim()
            if ($shortPath -and ($shortPath -notmatch ' ') -and (Test-Path $shortPath)) {
                Write-Log "Path has spaces - using 8.3 short path: $shortPath"
                $mcpRemotePath = $shortPath
            }
            else {
                Write-Log "WARNING: Could not shorten path (8.3 names may be disabled) - spaces may cause issues"
            }
        }
        catch {
            Write-Log "WARNING: Could not get short path: $_"
        }
    }

    # 3. Fetch registry from GitHub
    Write-Log "Fetching registry from $RegistryUrl"
    try {
        $registryRaw = Invoke-WebRequest -Uri $RegistryUrl -UseBasicParsing -TimeoutSec 15
        $registry = $registryRaw.Content | ConvertFrom-Json
    }
    catch {
        Write-Log "ERROR: Failed to fetch registry: $_"
        return
    }

    if (-not $registry.servers) {
        Write-Log "ERROR: Registry contains no servers"
        return
    }
    Write-Log "Registry fetched: $($registry.servers.Count) server(s) found"

    # 4. Read or create claude_desktop_config.json
    $configDir = Split-Path $ConfigPath -Parent
    if (-not (Test-Path $configDir)) {
        New-Item -ItemType Directory -Path $configDir -Force | Out-Null
        Write-Log "Created config directory: $configDir"
    }

    $config = $null
    if (Test-Path $ConfigPath) {
        try {
            $configRaw = Get-Content -Path $ConfigPath -Raw -Encoding UTF8
            if (-not [string]::IsNullOrWhiteSpace($configRaw)) {
                $config = $configRaw | ConvertFrom-Json
            }
        }
        catch {
            Write-Log "ERROR: Failed to parse existing config - backing up and starting fresh: $_"
            $backupName = "claude_desktop_config.backup." + (Get-Date -Format "yyyyMMdd-HHmmss") + ".json"
            Copy-Item $ConfigPath (Join-Path $configDir $backupName) -Force
        }
    }
    else {
        Write-Log "Config file not found - creating new one"
    }

    if ($null -eq $config) {
        $config = New-Object PSObject
    }

    $hasServers = $false
    try { $hasServers = $null -ne $config.mcpServers } catch {}
    if (-not $hasServers) {
        $config | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue (New-Object PSObject) -Force
    }

    $changesMade = $false

    # 5. Process each server in registry
    foreach ($server in $registry.servers) {
        $key          = $server.claude_config_key
        $rawUrl       = $server.railway_url.TrimEnd("/")
        $mcpUrl       = "$rawUrl/mcp"
        $tokenEnvVar  = $server.token_env_var
        Write-Log "Processing server: $($server.name) (key: $key)"

        # Resolve the bearer token (machine -> user -> process env var)
        $token = [System.Environment]::GetEnvironmentVariable($tokenEnvVar, "Machine")
        if (-not $token) { $token = [System.Environment]::GetEnvironmentVariable($tokenEnvVar, "User") }
        if (-not $token) { $token = [System.Environment]::GetEnvironmentVariable($tokenEnvVar, "Process") }

        if (-not $token) {
            # No token stored - show a friendly GUI prompt so the user can paste from Bitwarden
            Write-Log "No token found for $($server.name) - showing prompt"
            try {
                $input = Show-TokenPrompt -ServerName $server.name -TokenEnvVar $tokenEnvVar
                if ([string]::IsNullOrWhiteSpace($input)) {
                    Write-Log "SKIP: No token entered for $($server.name)"
                    continue
                }
                $token = $input.Trim()
                # Save for future runs
                try {
                    [System.Environment]::SetEnvironmentVariable($tokenEnvVar, $token, "Machine")
                    Write-Log "Saved token as machine-level env var: $tokenEnvVar"
                }
                catch {
                    [System.Environment]::SetEnvironmentVariable($tokenEnvVar, $token, "User")
                    Write-Log "Saved token as user-level env var: $tokenEnvVar"
                }
            }
            catch {
                Write-Log "SKIP: Could not show prompt for $($server.name): $_"
                continue
            }
        }

        # Escape % as %% so cmd.exe does not expand e.g. %HIuIlD5 as an env var
        $tokenForCmd = $token -replace '%', '%%'

        # Check if entry already exists and is fully up to date
        $existingServers = $config.mcpServers
        $alreadyExists = $false
        try { $alreadyExists = $null -ne $existingServers.$key } catch {}

        $entry = New-Object PSObject
        $entry | Add-Member -NotePropertyName "command" -NotePropertyValue $mcpRemotePath
        $entry | Add-Member -NotePropertyName "args" -NotePropertyValue @(
            $mcpUrl,
            "--header", "Authorization: Bearer $tokenForCmd"
        )

        if ($alreadyExists) {
            $existing = $existingServers.$key
            $existingUrl        = ""
            $existingCommand    = ""
            $existingAuthHeader = ""
            try {
                if ($existing.args) {
                    $existingUrl        = $existing.args[0]
                    if ($existing.args.Count -ge 3) { $existingAuthHeader = $existing.args[2] }
                }
                if ($existing.command) { $existingCommand = $existing.command }
            }
            catch {}
            $expectedAuthHeader = "Authorization: Bearer $tokenForCmd"
            if ($existingUrl -eq $mcpUrl -and $existingCommand -eq $mcpRemotePath -and $existingAuthHeader -eq $expectedAuthHeader) {
                Write-Log "SKIP: $($server.name) already configured correctly"
                continue
            }
            Write-Log "UPDATE: $($server.name) (command: $existingCommand -> $mcpRemotePath, url: $existingUrl -> $mcpUrl)"
        }
        else {
            Write-Log "ADD: $($server.name) is new - adding to config"
        }

        if ($alreadyExists) {
            $existingServers.PSObject.Properties.Remove($key)
        }
        $existingServers | Add-Member -NotePropertyName $key -NotePropertyValue $entry
        $changesMade = $true
    }

    # 6. Write updated config
    if ($changesMade) {
        $json = $config | ConvertTo-Json -Depth 10
        # Write UTF-8 without BOM - Claude Desktop's JSON parser rejects the BOM
        [System.IO.File]::WriteAllText($ConfigPath, $json, (New-Object System.Text.UTF8Encoding $false))
        Write-Log "Config written to $ConfigPath"

        # Restart Claude Desktop if it is running
        $claudeProcess = Get-Process -Name "Claude" -ErrorAction SilentlyContinue
        if ($claudeProcess) {
            Write-Log "Restarting Claude Desktop..."
            Stop-Process -Name "Claude" -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            $claudeExe = "$env:LOCALAPPDATA\Claude\Claude.exe"
            if (Test-Path $claudeExe) {
                Start-Process $claudeExe
                Write-Log "Claude Desktop restarted"
            }
            else {
                Write-Log "WARNING: Claude.exe not found at $claudeExe - skipping relaunch"
            }
        }
        else {
            Write-Log "Claude Desktop not running - config updated, will take effect on next launch"
        }
    }
    else {
        Write-Log "No changes needed - config is up to date"
    }

    Write-Log "--- Carimans MCP Updater finished ---"
}

Main
