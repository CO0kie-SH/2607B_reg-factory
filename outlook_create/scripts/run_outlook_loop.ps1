param(
    [int]$Count = 1,
    [int]$TargetPool = 0,
    [string]$MaxPress = "3",
    [int]$Timeout = 180,
    [int]$Sleep = 5,
    [int]$SleepWhenFull = 60,
    [switch]$NoRotate,
    [switch]$ConfirmBeforeRegister
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RepoRoot

$argsList = @(
    "outlook_reg_loop.py",
    "--count", $Count,
    "--target-pool", $TargetPool,
    "--max-press", $MaxPress,
    "--timeout", $Timeout,
    "--sleep", $Sleep,
    "--sleep-when-full", $SleepWhenFull
)

if ($NoRotate) {
    $argsList += "--no-rotate"
}
if ($ConfirmBeforeRegister) {
    $argsList += "--confirm-before-register"
}

Write-Host "[outlook_create] repo root: $RepoRoot"
Write-Host "[outlook_create] running: py -3 $($argsList -join ' ')"
& py -3 @argsList
exit $LASTEXITCODE
