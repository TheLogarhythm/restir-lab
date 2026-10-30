param([switch]$CheckOnly, [ValidateRange(1,8)][int]$Jobs=4)
$ErrorActionPreference="Stop"
$arguments=@("-B",(Join-Path $PSScriptRoot "build.py"),"--jobs",$Jobs)
if ($CheckOnly) { $arguments += "--check-only" }
& python @arguments
if ($LASTEXITCODE -ne 0) { throw "Falcor setup failed; see build/falcor logs." }
