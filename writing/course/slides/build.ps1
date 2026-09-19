param([switch]$Images)
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$outputDir = Join-Path $repoRoot 'build/slides'
$source = Join-Path $PSScriptRoot 'pitch.md'
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

function Invoke-Marp {
    & npx.cmd --yes '@marp-team/marp-cli@4.5.1' $source --html @args
    if ($LASTEXITCODE -ne 0) { throw "Marp failed with exit code $LASTEXITCODE" }
}

Invoke-Marp --output (Join-Path $outputDir 'pitch.html')
# Embed local illustrations so the HTML can be opened or shared on its own.
$htmlPath = Join-Path $outputDir 'pitch.html'
$html = [IO.File]::ReadAllText($htmlPath)
foreach ($asset in Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'assets') -Filter '*.png') {
    $uri = 'data:image/png;base64,' + [Convert]::ToBase64String([IO.File]::ReadAllBytes($asset.FullName))
    $html = $html.Replace('src="assets/' + $asset.Name + '"', 'src="' + $uri + '"')
}
[IO.File]::WriteAllText($htmlPath, $html, [Text.UTF8Encoding]::new($false))
Invoke-Marp --pdf --pdf-notes --allow-local-files --output (Join-Path $outputDir 'pitch.pdf')
Invoke-Marp --notes --output (Join-Path $outputDir 'pitch-notes.txt')
if ($Images) {
    Invoke-Marp --images png --image-scale 1.5 --allow-local-files --output (Join-Path $outputDir 'pitch.png')
}
Write-Output "Slides: $outputDir"
