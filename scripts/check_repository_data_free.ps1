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
            $forbiddenPatterns | Where-Object {
                $path -like $_
            }
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
