param(
    [switch]$Media,
    [switch]$PreviewImages,
    [switch]$Notes,
    [ValidateSet('chrome','edge','auto')][string]$Browser = 'chrome'
)
$ErrorActionPreference = 'Stop'
$progressRoot = Split-Path $PSScriptRoot
$source = Join-Path $progressRoot 'source/progress.md'
if ($Media) {
    & python -B (Join-Path $PSScriptRoot 'build_media.py')
    if ($LASTEXITCODE -ne 0) { throw 'Video build failed' }
}
& python -B (Join-Path $PSScriptRoot 'build.py')
if ($LASTEXITCODE -ne 0) { throw 'Comparison build failed' }
$node = (Get-Command node.exe).Source
$marp = $null
$cache = Join-Path $env:LOCALAPPDATA 'npm-cache/_npx'
foreach ($entry in Get-ChildItem -LiteralPath $cache -Directory -ErrorAction SilentlyContinue) {
    $package = Join-Path $entry.FullName 'node_modules/@marp-team/marp-cli/package.json'
    if (Test-Path -LiteralPath $package) {
        $info = Get-Content -LiteralPath $package -Raw | ConvertFrom-Json
        if ($info.version -eq '4.5.1') { $marp = Join-Path (Split-Path $package) 'marp-cli.js'; break }
    }
}
function Invoke-Marp {
    if ($marp) { & $node $marp $source --html @args }
    else { & npx.cmd --yes '@marp-team/marp-cli@4.5.1' $source --html @args }
    if ($LASTEXITCODE -ne 0) { throw "Marp failed: $LASTEXITCODE" }
}
$htmlPath = Join-Path $progressRoot 'progress.html'
Invoke-Marp --output $htmlPath
$html = [System.IO.File]::ReadAllText($htmlPath)
$html = $html.Replace('src="../assets/', 'src="assets/').Replace('poster="../assets/', 'poster="assets/').Replace('href="../comparison.html', 'href="comparison.html')
[System.IO.File]::WriteAllText($htmlPath, $html, [System.Text.UTF8Encoding]::new($false))
if ($PreviewImages -or $Notes) {
    $preview = Join-Path $progressRoot 'build'
    New-Item -ItemType Directory -Force -Path $preview | Out-Null
    if ($PreviewImages) { Invoke-Marp --images png --image-scale 1.5 --allow-local-files --browser $Browser --output (Join-Path $preview 'slide.png') }
    if ($Notes) { Invoke-Marp --notes --output (Join-Path $preview 'speaker-notes.txt') }
}
Write-Output 'Built comparison.html and progress.html. Source: source/progress.md'
