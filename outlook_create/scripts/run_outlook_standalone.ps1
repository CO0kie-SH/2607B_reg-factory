param(
    [int]$Count = 1,
    [int]$Concurrency = 1,
    [ValidateSet("auto", "protocol", "headless", "browser")]
    [string]$Mode = "browser",
    [int]$Timeout = 300,
    [string]$ProxyFile = "",
    [switch]$NoProxy,
    [switch]$NoVerify,
    [switch]$ConfirmBeforeRegister
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RepoRoot

$argsList = @(
    "register_outlook_standalone.py",
    "--count", $Count,
    "--concurrency", $Concurrency,
    "--mode", $Mode,
    "--timeout", $Timeout
)

if ($ProxyFile -ne "") {
    $argsList += @("--proxy-file", $ProxyFile)
}
if ($NoProxy) {
    $argsList += "--no-proxy"
}
if ($NoVerify) {
    $argsList += "--no-verify"
}
if ($ConfirmBeforeRegister) {
    $argsList += "--confirm-before-register"
}

Write-Host "[outlook_create] repo root: $RepoRoot"
Write-Host "[outlook_create] running: py -3 $($argsList -join ' ')"
& py -3 @argsList
exit $LASTEXITCODE
