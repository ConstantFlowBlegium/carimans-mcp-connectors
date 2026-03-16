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

        if ($alreadyExists) {
            $existing = $existingServers.$key
            # Check if URL matches (could be in args array or old url field)
            $existingUrl = ""
            try {
                if ($existing.args) {
                    # npx mcp-remote format: URL is the 3rd arg (index 2)
                    $existingUrl = $existing.args[2]
                } elseif ($existing.url) {
                    $existingUrl = $existing.url
                }
            } catch {}
            if ($existingUrl -eq $mcpUrl) {
                Write-Log "SKIP: $($server.name) already configured with correct URL"
                continue
            }
            Write-Log "UPDATE: $($server.name) URL changed from $existingUrl to $mcpUrl"
        }
        else {
            Write-Log "ADD: $($server.name) is new - adding to config"
        }

        # Build the MCP server entry using npx mcp-remote bridge
        # This works with all Claude Desktop versions (no native HTTP transport needed)
        $envObj = New-Object PSObject
        $envObj | Add-Member -NotePropertyName $tokenEnvVar -NotePropertyValue $token
        $entry = New-Object PSObject
        $entry | Add-Member -NotePropertyName "command" -NotePropertyValue "npx"
        $entry | Add-Member -NotePropertyName "args" -NotePropertyValue @(
            "-y", "@anthropic-ai/mcp-remote",
            $mcpUrl,
            "--header", "Authorization:`${$tokenEnvVar}"
        )
        $entry | Add-Member -NotePropertyName "env" -NotePropertyValue $envObj

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
