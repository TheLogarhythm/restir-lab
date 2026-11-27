[CmdletBinding()]
param(
    [string]$Runtime,
    [switch]$Prepare,
    [ValidateSet('classroom', 'all')]
    [string]$Acceptance,
    [switch]$PrecompileShaders,
    [string]$Scene,
    [ValidateSet('Raw', 'Accumulation', 'NRD')]
    [string]$Display = 'Raw',
    [ValidateRange(64, 7680)]
    [int]$Width = 1920,
    [ValidateRange(64, 4320)]
    [int]$Height = 1080,
    [string]$OutputDirectory,
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    if ($PrecompileShaders -and ($Acceptance -or $PSBoundParameters.ContainsKey('Display'))) {
        throw '-PrecompileShaders exercises every display mode and cannot be combined with -Acceptance or -Display.'
    }
    if (!$Runtime) {
        $action = '--locate'
        if ($Prepare -or !(Test-Path -LiteralPath 'build/falcor-live-demo.json' -PathType Leaf)) {
            $action = '--prepare'
        }
        $prepared = & $Python -B -m scripts.falcor.live_runtime $action
        if ($LASTEXITCODE -ne 0 -or !$prepared) { throw 'Could not prepare the Falcor demo runtime.' }
        $Runtime = ($prepared | Select-Object -Last 1).Trim()
    }
    if (!(Test-Path -LiteralPath (Join-Path $Runtime 'Mogwai.exe') -PathType Leaf)) {
        throw "Mogwai.exe is missing in $Runtime"
    }
    if (!$OutputDirectory) {
        $runId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
        $runRoot = if ($PrecompileShaders) { 'runs/falcor-shader-precompile' } else { 'runs/falcor-live-demo' }
        $OutputDirectory = Join-Path $runRoot $runId
    }
    $sessionArgs = @('-B', '-m', 'scripts.falcor.live_demo', '--runtime', $Runtime,
                     '--output', $OutputDirectory, '--width', $Width, '--height', $Height)
    if (!$Acceptance -and !$PrecompileShaders) {
        $displayNames = @{ Raw = 'Raw'; Accumulation = 'Accumulation'; NRD = 'NRD' }
        $sessionArgs += @('--mode', $displayNames[$Display])
    }
    if ($Scene) { $sessionArgs += @('--scene', $Scene) }
    if ($Acceptance) { $sessionArgs += @('--acceptance', $Acceptance) }
    if ($PrecompileShaders) { $sessionArgs += '--precompile-shaders' }
    Write-Host "Demo run directory: $OutputDirectory"
    & $Python @sessionArgs
    if ($LASTEXITCODE -ne 0) { throw "Falcor demo exited with code $LASTEXITCODE. See $OutputDirectory." }
} finally {
    Pop-Location
}
