[CmdletBinding()]
param(
    [switch]$ConfigureCodex,
    [switch]$ConfigureHooks,
    [string]$PythonExecutable = "",
    [string]$InstallDirectory = ""
)

$ErrorActionPreference = "Stop"
$sourceRoot = Split-Path -Parent $PSScriptRoot
$codexHome = Join-Path $env:USERPROFILE ".codex"
if ([string]::IsNullOrWhiteSpace($InstallDirectory)) {
    $InstallDirectory = Join-Path $codexHome "codex_memory"
}
$InstallDirectory = [System.IO.Path]::GetFullPath($InstallDirectory)

function Get-PythonSpec {
    if (-not [string]::IsNullOrWhiteSpace($PythonExecutable)) {
        if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw "Python executable not found: $PythonExecutable" }
        return [pscustomobject]@{ Executable = [System.IO.Path]::GetFullPath($PythonExecutable); PrefixArgs = @() }
    }
    if (-not [string]::IsNullOrWhiteSpace($env:CODEX_MEMORY_PYTHON) -and (Test-Path -LiteralPath $env:CODEX_MEMORY_PYTHON -PathType Leaf)) {
        return [pscustomobject]@{ Executable = $env:CODEX_MEMORY_PYTHON; PrefixArgs = @() }
    }
    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundledPython -PathType Leaf) {
        return [pscustomobject]@{ Executable = $bundledPython; PrefixArgs = @() }
    }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        return [pscustomobject]@{
            Executable = $python.Source
            PrefixArgs = @()
        }
    }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        return [pscustomobject]@{
            Executable = $py.Source
            PrefixArgs = @("-3")
        }
    }
    throw "Python 3.10 or newer was not found. Install Python and run this script again."
}

function Quote-TomlLiteral([string]$value) {
    return ($value | ConvertTo-Json -Compress)
}

function Add-PropertyIfMissing($object, [string]$name, $value) {
    if ($null -eq $object.PSObject.Properties[$name]) {
        $object | Add-Member -MemberType NoteProperty -Name $name -Value $value
    }
}

function New-HookCommand([string]$pythonCommand, [string]$hookPath, [string]$action) {
    return "$pythonCommand `"$hookPath`" $action"
}

function Set-HookEvent(
    $hooksConfig,
    [string]$eventName,
    [string]$pythonCommand,
    [string]$hookPath,
    [string]$action,
    [string]$statusMessage,
    [string]$matcher = "",
    [int]$additionalContextLimit = 0
) {
    $eventProperty = $hooksConfig.hooks.PSObject.Properties[$eventName]
    $existingEntries = @()
    if ($null -ne $eventProperty) {
        $existingEntries = @($eventProperty.Value)
    }

    $retainedEntries = New-Object System.Collections.Generic.List[object]
    foreach ($entry in $existingEntries) {
        if ($null -eq $entry) {
            continue
        }
        $entryHooks = @()
        if ($null -ne $entry.PSObject.Properties["hooks"]) {
            $entryHooks = @($entry.hooks)
        }
        $filteredHooks = @(
            $entryHooks | Where-Object {
                $command = [string]$_.command
                $command -notmatch "codex_memory_hook\.py"
            }
        )
        if ($filteredHooks.Count -gt 0) {
            $entry.hooks = $filteredHooks
            [void]$retainedEntries.Add($entry)
        }
    }

    $command = New-HookCommand $pythonCommand $hookPath $action
    $hook = [pscustomobject]@{
        type = "command"
        command = $command
        command_windows = $command
        statusMessage = $statusMessage
    }
    if ($additionalContextLimit -gt 0) {
        $hook | Add-Member -MemberType NoteProperty -Name additionalContextLimit -Value $additionalContextLimit
    }
    if ($action -eq "stop") {
        $hook | Add-Member -MemberType NoteProperty -Name timeout -Value 30
    }

    $newEntry = [pscustomobject]@{ hooks = @($hook) }
    if (-not [string]::IsNullOrWhiteSpace($matcher)) {
        $newEntry | Add-Member -MemberType NoteProperty -Name matcher -Value $matcher
    }
    [void]$retainedEntries.Add($newEntry)

    if ($null -ne $eventProperty) {
        $hooksConfig.hooks.$eventName = @($retainedEntries)
    } else {
        $hooksConfig.hooks | Add-Member -MemberType NoteProperty -Name $eventName -Value @($retainedEntries)
    }
}

$python = Get-PythonSpec
$pythonCommand = "`"$($python.Executable)`""
if ($python.PrefixArgs.Count -gt 0) {
    $pythonCommand += " " + ($python.PrefixArgs -join " ")
}

New-Item -ItemType Directory -Force -Path $InstallDirectory | Out-Null
$skillInstallDirectory = Join-Path $codexHome "skills\codex-memory"
New-Item -ItemType Directory -Force -Path (Join-Path $skillInstallDirectory "agents") | Out-Null
$filesToInstall = @(
    "codex_memory_core.py",
    "codex_memory_features.py",
    "codex_memory_dashboard.py",
    "codex_memory_mcp.py",
    "codex_memory_hook.py",
    "codex_memory_vault.pyw"
)
foreach ($file in $filesToInstall) {
    if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot $file) -PathType Leaf)) { throw "Incomplete package: $file" }
}
foreach ($file in $filesToInstall) {
    Copy-Item -LiteralPath (Join-Path $sourceRoot $file) -Destination (Join-Path $InstallDirectory $file) -Force
}
$installedConfig = Join-Path $InstallDirectory 'config'
New-Item -ItemType Directory -Force -Path $installedConfig | Out-Null
Copy-Item -LiteralPath (Join-Path $sourceRoot 'config\memory-settings.json.example') -Destination (Join-Path $installedConfig 'memory-settings.json.example') -Force
$dashboardLauncher = Join-Path $sourceRoot '启动 Codex 记忆面板.bat'
if (Test-Path -LiteralPath $dashboardLauncher -PathType Leaf) {
    Copy-Item -LiteralPath $dashboardLauncher -Destination $InstallDirectory -Force
}
Copy-Item -LiteralPath (Join-Path $sourceRoot "skills\codex-memory\SKILL.md") -Destination (Join-Path $skillInstallDirectory "SKILL.md") -Force
Copy-Item -LiteralPath (Join-Path $sourceRoot "skills\codex-memory\agents\openai.yaml") -Destination (Join-Path $skillInstallDirectory "agents\openai.yaml") -Force

Write-Host "Installed Codex memory files to $InstallDirectory"
Write-Host "Installed Codex skill to $skillInstallDirectory"
Write-Host "Database remains local at $([Environment]::GetFolderPath('LocalApplicationData'))\CodexMemoryVault\memory.db"

if (-not $ConfigureCodex -and -not $ConfigureHooks) {
    Write-Host "Use -ConfigureCodex for MCP; add -ConfigureHooks only when you explicitly want lifecycle hook configuration."
    exit 0
}

New-Item -ItemType Directory -Force -Path $codexHome | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$hookPath = Join-Path $InstallDirectory "codex_memory_hook.py"

if ($ConfigureHooks) {
$hooksPath = Join-Path $codexHome "hooks.json"
$hooksConfig = [pscustomobject]@{
    description = "Codex local long-term memory layer"
    hooks = [pscustomobject]@{}
}
if (Test-Path -LiteralPath $hooksPath) {
    $rawHooks = Get-Content -LiteralPath $hooksPath -Raw
    if (-not [string]::IsNullOrWhiteSpace($rawHooks)) {
        $hooksConfig = $rawHooks | ConvertFrom-Json
    }
}
Add-PropertyIfMissing $hooksConfig "hooks" ([pscustomobject]@{})
if (-not $hooksConfig.PSObject.Properties["description"]) {
    $hooksConfig | Add-Member -MemberType NoteProperty -Name description -Value "Codex local long-term memory layer"
}

if (Test-Path -LiteralPath $hooksPath) {
    Copy-Item -LiteralPath $hooksPath -Destination "$hooksPath.bak-codex-memory-$timestamp" -Force
}
Set-HookEvent $hooksConfig "SessionStart" $pythonCommand $hookPath "session-start" "Load Codex long-term memory" "startup|resume|clear|compact" 5000
Set-HookEvent $hooksConfig "UserPromptSubmit" $pythonCommand $hookPath "prompt" "Search Codex long-term memory"
Set-HookEvent $hooksConfig "Stop" $pythonCommand $hookPath "stop" "Curate current Codex turn"
$hooksConfig | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $hooksPath -Encoding UTF8
Write-Host "Updated hooks: $hooksPath"
}

if (-not $ConfigureCodex) {
    Write-Host "Runtime installed. Requested hook configuration is complete."
    exit 0
}

$configPath = Join-Path $codexHome "config.toml"
$tomlArguments = @($python.PrefixArgs) + @((Join-Path $InstallDirectory "codex_memory_mcp.py"))
$tomlArgumentsText = (($tomlArguments | ForEach-Object { Quote-TomlLiteral ([string]$_) }) -join ", ")
$tomlBlock = @"
# BEGIN CODEX MEMORY
[mcp_servers.codex_memory]
enabled = true
command = $(Quote-TomlLiteral $python.Executable)
args = [$tomlArgumentsText]
startup_timeout_sec = 30
tool_timeout_sec = 60
# END CODEX MEMORY
"@
$existingToml = ""
if (Test-Path -LiteralPath $configPath) {
    $existingToml = Get-Content -LiteralPath $configPath -Raw
}
$markerPattern = "(?ms)# BEGIN CODEX MEMORY.*?# END CODEX MEMORY"
if ($existingToml -match $markerPattern) {
    $newToml = [regex]::Replace($existingToml, $markerPattern, $tomlBlock.Trim())
    Copy-Item -LiteralPath $configPath -Destination "$configPath.bak-codex-memory-$timestamp" -Force
    $newToml | Set-Content -LiteralPath $configPath -Encoding UTF8
    Write-Host "Updated the marked Codex memory MCP block in $configPath"
} elseif ($existingToml -match "(?m)^\[mcp_servers\.codex_memory\]") {
    Write-Warning "An existing unmarked [mcp_servers.codex_memory] block was found in $configPath; it was left unchanged. Check its paths manually."
} else {
    if (-not [string]::IsNullOrWhiteSpace($existingToml) -and -not $existingToml.EndsWith("`n")) {
        $existingToml += "`r`n"
    }
    ($existingToml + $tomlBlock) | Set-Content -LiteralPath $configPath -Encoding UTF8
    Write-Host "Added the Codex memory MCP block to $configPath"
}

Write-Host "Restart Codex Desktop completely so it reloads the MCP server. Hook runtime success must be checked separately in a real conversation."
