param(
    [switch]$Media,
    [switch]$Figures,
    [switch]$PreviewImages,
    [switch]$Pdf,
    [switch]$Pptx,
    [string]$Python = 'python',
    [string]$Marp,
    [ValidateSet('chrome','edge','auto')][string]$Browser = 'chrome'
)
$ErrorActionPreference = 'Stop'
$finalRoot = Split-Path $PSScriptRoot
$repoRoot = [IO.Path]::GetFullPath((Join-Path $finalRoot '../..'))
$buildRoot = Join-Path $finalRoot 'build'
$theme = Join-Path $finalRoot 'source/theme.css'
New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null
function Invoke-Python([string]$Script) {
    & $Python -B (Join-Path $PSScriptRoot $Script) @args
    if ($LASTEXITCODE -ne 0) { throw "Python failed: $Script" }
}
# Rebuilding the deck alone never regenerates historical/derived media or appendix prose.
if ($Figures) {
    foreach ($script in @('build_diagrams.py','build_figures.py','build_results_panels.py','build_appendix.py')) {
        Invoke-Python $script
    }
}
if ($Media) { Invoke-Python 'build_media.py' }
$node = (Get-Command node.exe).Source
$candidates = @()
if ($Marp) { $candidates += $Marp }
$candidates += Join-Path $repoRoot 'node_modules/@marp-team/marp-cli/marp-cli.js'
if ($env:LOCALAPPDATA) {
    $cache = Join-Path $env:LOCALAPPDATA 'npm-cache/_npx'
    foreach ($entry in Get-ChildItem -LiteralPath $cache -Directory -ErrorAction SilentlyContinue) {
        $candidates += Join-Path $entry.FullName 'node_modules/@marp-team/marp-cli/marp-cli.js'
    }
}
$marpCli = $null
foreach ($candidate in $candidates) {
    if (-not(Test-Path -LiteralPath $candidate)) { continue }
    $package = Join-Path (Split-Path $candidate) 'package.json'
    if ((Get-Content -LiteralPath $package -Raw | ConvertFrom-Json).version -eq '4.5.1') {
        $marpCli = $candidate
        break
    }
}
if (-not $marpCli) { throw 'Install @marp-team/marp-cli@4.5.1 locally, or supply -Marp. No dependencies are downloaded automatically.' }
function Invoke-Marp([string]$Source) {
    & $node $marpCli $Source --html --theme-set $theme @args
    if ($LASTEXITCODE -ne 0) { throw 'Marp build failed' }
}
foreach ($deck in @('final','appendix')) {
    $source = Join-Path $finalRoot "source/$deck.md"
    $htmlPath = Join-Path $finalRoot "$deck.html"
    Invoke-Marp $source --output $htmlPath
    $html = [IO.File]::ReadAllText($htmlPath).Replace('src="../assets/','src="assets/').Replace('poster="../assets/','poster="assets/')
    if ($deck -eq 'final') { $html = $html.Replace('</body>','<script src="source/playback.js"></script></body>') }
    [IO.File]::WriteAllText($htmlPath,$html,[Text.UTF8Encoding]::new($false))
    Invoke-Marp $source --notes --output (Join-Path $buildRoot "$deck-notes.txt")
    if ($PreviewImages) {
        Invoke-Marp $source --images png --image-scale 1.5 --allow-local-files --browser $Browser --output (Join-Path $buildRoot "$deck.png")
    }
    if ($Pdf) {
        Invoke-Marp $source --pdf --allow-local-files --browser $Browser --output (Join-Path $buildRoot "$deck.pdf")
    }
    if ($Pptx -and $deck -eq 'final') {
        Invoke-Python 'build_media.py' --pptx-inputs (Join-Path $buildRoot 'pptx-video-inputs.json')
        Invoke-Marp $source --pptx --allow-local-files --browser $Browser --output (Join-Path $buildRoot 'final-posters.pptx')
        & (Join-Path $PSScriptRoot 'export_video_pptx.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'Embedded-video PPTX export failed' }
    }
}
Write-Output "Built presentation in $finalRoot"
