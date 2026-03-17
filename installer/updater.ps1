# Carimans MCP Connectors - Auto-Updater
# Fetches the MCP registry from GitHub and syncs claude_desktop_config.json

$ErrorActionPreference = "Stop"

$RegistryUrl = "https://raw.githubusercontent.com/ConstantFlowBlegium/carimans-mcp-connectors/main/registry/mcp-registry.json"
$ConfigPath = "$env:APPDATA\Claude\claude_desktop_config.json"
$LogFile = "$env:TEMP\carimans-mcp-connectors-updater.log"

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Main {
    Write-Log "--- Carimans MCP Updater started ---"

    # 0. Ensure mcp-remote is globally installed (npx doesn't work reliably on Windows)
    Write-Log "Ensuring mcp-remote is installed globally..."
    try {
        $npmOutput = & npm list -g mcp-remote 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Installing mcp-remote globally..."
            & npm install -g mcp-remote 2>&1 | Out-Null
            Write-Log "mcp-remote installed"
        } else {
            Write-Log "mcp-remote already installed"
        }
    }
    catch {
        Write-Log "WARNING: Could not install mcp-remote: $_"
    }

    # Resolve the full path to mcp-remote.cmd so Claude Desktop can launch it directly.
    # Must be .cmd specifically — Claude Desktop (Electron) cannot execute .ps1 files directly.
    $mcpRemotePath = $null
    try {
        # Preferred: look for mcp-remote.cmd in the global npm prefix directory
        $npmPrefix = (& npm prefix -g 2>&1).Trim()
        $candidate = Join-Path $npmPrefix "mcp-remote.cmd"
        if (Test-Path $candidate) {
            $mcpRemotePath = $candidate
        }
    }
    catch {}
    if (-not $mcpRemotePath) {
        # Fallback: walk Get-Command results and pick the .cmd file
        try {
            $resolved = (Get-Command "mcp-remote" -ErrorAction Stop).Source
            if ($resolved -like "*.cmd") {
                $mcpRemotePath = $resolved
            } else {
                $cmdSibling = [System.IO.Path]::ChangeExtension($resolved, ".cmd")
                if (Test-Path $cmdSibling) {
                    $mcpRemotePath = $cmdSibling
                } else {
                    $mcpRemotePath = $resolved  # last resort
                }
            }
        }
        catch {
            Write-Log "WARNING: Could not resolve mcp-remote path — falling back to 'mcp-remote'"
            $mcpRemotePath = "mcp-remote"
        }
    }
    Write-Log "Resolved mcp-remote path: $mcpRemotePath"

    # 1. Fetch registry from GitHub
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

    # 2. Read or create claude_desktop_config.json
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
            $backupPath = Join-Path $configDir $backupName
            Copy-Item $ConfigPath $backupPath -Force
        }
    }
    else {
        Write-Log "Config file not found - creating new one"
    }

    if ($null -eq $config) {
        $config = New-Object PSObject
    }

    # Ensure mcpServers key exists
    $hasServers = $false
    try { $hasServers = $null -ne $config.mcpServers } catch {}
    if (-not $hasServers) {
        $config | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue (New-Object PSObject) -Force
    }

    $changesMade = $false
    $isNonInteractive = [Environment]::GetCommandLineArgs() -contains "-NonInteractive"
    $interactive = [Environment]::UserInteractive -and (-not $isNonInteractive)

    # 3. Process each server in registry
    foreach ($server in $registry.servers) {
        $key = $server.claude_config_key
        $rawUrl = $server.railway_url.TrimEnd("/")
        $mcpUrl = "$rawUrl/mcp"
        Write-Log "Processing server: $($server.name) (key: $key)"

        # Resolve the bearer token
        $tokenEnvVar = $server.token_env_var
        $token = [System.Environment]::GetEnvironmentVariable($tokenEnvVar, "Machine")
        if (-not $token) {
            $token = [System.Environment]::GetEnvironmentVariable($tokenEnvVar, "User")
        }
        if (-not $token) {
            $token = [System.Environment]::GetEnvironmentVariable($tokenEnvVar, "Process")
        }

        if (-not $token) {
            if ($interactive) {
                Write-Host ""
                Write-Host "No token found for $($server.name) (env var: $tokenEnvVar)"
                $token = Read-Host "Please enter the access token for $($server.name)"
                if ([string]::IsNullOrWhiteSpace($token)) {
                    Write-Log "SKIP: No token provided for $($server.name) - skipping"
                    continue
                }
                # Save as machine-level env var for future runs
                try {
                    [System.Environment]::SetEnvironmentVariable($tokenEnvVar, $token, "Machine")
                    Write-Log "Saved token as machine-level env var: $tokenEnvVar"
                }
                catch {
                    # If not admin, fall back to user-level
                    [System.Environment]::SetEnvironmentVariable($tokenEnvVar, $token, "User")
                    Write-Log "Saved token as user-level env var (no admin rights): $tokenEnvVar"
                }
            }
            else {
                Write-Log "SKIP: No token found for $($server.name) and running non-interactively - skipping"
                continue
            }
        }

        # Check if entry already exists and whether it needs updating
        $existingServers = $config.mcpServers
        $alreadyExists = $false
        try { $alreadyExists = $null -ne $existingServers.$key } catch {}

        # Build the MCP server entry using the resolved mcp-remote path
        # npx doesn't work reliably on Windows — the process exits immediately
        $entry = New-Object PSObject
        $entry | Add-Member -NotePropertyName "command" -NotePropertyValue $mcpRemotePath
        $entry | Add-Member -NotePropertyName "args" -NotePropertyValue @(
            $mcpUrl,
            "--header", "Authorization: Bearer $token"
        )

        if ($alreadyExists) {
            $existing = $existingServers.$key
            # Check if both URL and command format are correct
            $existingUrl = ""
            $existingCommand = ""
            try {
                if ($existing.args) { $existingUrl = $existing.args[0] }
                if ($existing.command) { $existingCommand = $existing.command }
            } catch {}
            if ($existingUrl -eq $mcpUrl -and $existingCommand -eq $mcpRemotePath) {
                Write-Log "SKIP: $($server.name) already configured correctly"
                continue
            }
            Write-Log "UPDATE: $($server.name) (command: $existingCommand -> $mcpRemotePath, url: $existingUrl -> $mcpUrl)"
        }
        else {
            Write-Log "ADD: $($server.name) is new - adding to config"
        }

        # Add or update the entry
        if ($alreadyExists) {
            $existingServers.PSObject.Properties.Remove($key)
        }
        $existingServers | Add-Member -NotePropertyName $key -NotePropertyValue $entry
        $changesMade = $true
    }

    # 4. Write updated config
    if ($changesMade) {
        $json = $config | ConvertTo-Json -Depth 10
        # Write UTF-8 without BOM — Claude Desktop's JSON parser rejects the BOM
        [System.IO.File]::WriteAllText($ConfigPath, $json, (New-Object System.Text.UTF8Encoding $false))
        Write-Log "Config written to $ConfigPath"

        # 5. Restart Claude Desktop if it is running
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
