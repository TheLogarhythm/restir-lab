# Delegate to the same build implementation used in the repository.
& (Join-Path $PSScriptRoot '../writing/final/tools/build.ps1') @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
