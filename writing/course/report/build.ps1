$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $buildDir = 'build/latex'
    $outputDir = '../../report'
    New-Item -Path $buildDir, $outputDir -ItemType Directory -Force | Out-Null
    & latexmk -pdf -interaction=nonstopmode -halt-on-error "-outdir=$buildDir" -jobname=report main.tex
    if ($LASTEXITCODE -ne 0) { throw 'Report compilation failed' }
    Copy-Item -LiteralPath (Join-Path $buildDir 'report.pdf') -Destination (Join-Path $outputDir 'report.pdf') -Force
} finally {
    Pop-Location
}
