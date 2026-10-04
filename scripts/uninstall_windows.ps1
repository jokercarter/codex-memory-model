[CmdletBinding()]
param(
    [string]$InstallDirectory = ""
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($InstallDirectory)) {
    $InstallDirectory = Join-Path $env:USERPROFILE ".codex\codex_memory"
}

$resolvedInstall = [System.IO.Path]::GetFullPath($InstallDirectory)
$expectedRoot = [System.IO.Path]::GetFullPath((Join-Path $env:USERPROFILE ".codex"))
$expectedPrefix = $expectedRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not $resolvedInstall.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove a directory outside the user's .codex directory: $resolvedInstall"
}
if (Test-Path -LiteralPath $resolvedInstall) {
    Remove-Item -LiteralPath $resolvedInstall -Recurse -Force
    Write-Host "Removed installed Codex memory source files: $resolvedInstall"
} else {
    Write-Host "No installed source directory found at $resolvedInstall"
}
Write-Host "The local database and Codex configuration were left unchanged. Remove them manually only if desired."
