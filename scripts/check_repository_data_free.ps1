[CmdletBinding()]
param(
    [switch]$Staged
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    if ($Staged) {
        $paths = @(git diff --cached --name-only --diff-filter=ACMR)
    } else {
        $paths = @(git ls-files)
    }
    $forbiddenPatterns = @(
        "*.db",
        "*.db-*",
        "*.sqlite",
        "*.sqlite-*",
        "*.sqlite3",
        "*.bak",
        "*.bak-*",
        "*.log",
        "*.jsonl",
        "*memory*.json",
        "CodexMemoryVault/*",
        ".codex_memory_vault/*"
    )
    $violations = @(
        $paths | Where-Object {
            $path = $_
            # Plugin metadata is configuration code, not a memory export. Its
            # filename contains "memory" by design, so exempt only standard
            # metadata locations inside a plugin package.
            if ($path -match '(^|[\\/])plugins[\\/][^\\/]+[\\/](\.codex-plugin[\\/]plugin\.json|\.mcp\.json)$') {
                return $false
            }
            foreach ($pattern in $forbiddenPatterns) {
                if ($path -like $pattern) {
                    return $true
                }
            }
            return $false
        }
    ) | Sort-Object -Unique
    if ($violations.Count -gt 0) {
        $details = $violations -join ([Environment]::NewLine)
        Write-Error ("Potential local memory artifacts are staged or tracked:" + [Environment]::NewLine + $details)
    }
    Write-Output "Repository data-free check passed."
}
finally {
    Pop-Location
}
