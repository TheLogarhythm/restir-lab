param([switch]$VerifyPlayback)
$ErrorActionPreference = 'Stop'
$finalRoot = Split-Path $PSScriptRoot
$buildRoot = Join-Path $finalRoot 'build'
$spec = Get-Content (Join-Path $buildRoot 'pptx-video-inputs.json') -Raw | ConvertFrom-Json
$videos = @($spec.videos | Where-Object { $_.deck -eq 'final' })
foreach ($video in $videos) {
 if ((Get-FileHash -LiteralPath $video.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $video.sha256) {
  throw "PPTX input video hash mismatch: $($video.path)"
 }
}
$app = New-Object -ComObject PowerPoint.Application
$deck = $null
try {
 $deck = $app.Presentations.Open((Join-Path $buildRoot 'final-posters.pptx'),$false,$false,$false)
 if ($deck.Slides.Count -ne $spec.slides) { throw 'Unexpected slide count' }
 $entries = @()
 foreach ($video in $videos) {
  $slide = $deck.Slides.Item([int]$video.slide)
  $shape = $slide.Shapes.AddMediaObject2([string]$video.path,0,-1,0,0,$deck.PageSetup.SlideWidth,$deck.PageSetup.SlideHeight)
  $shape.Name = 'Embedded demo ' + [IO.Path]::GetFileNameWithoutExtension($video.path)
  $play = $shape.AnimationSettings.PlaySettings
  $play.PlayOnEntry = -1
  $play.LoopUntilStopped = -1
  $play.RewindMovie = -1
  $play.HideWhileNotPlaying = 0
  $entries += @{slide=[int]$video.slide;shape_id=$shape.Id;path=[string]$video.path;sha256=$video.sha256;autoplay=$true;loop=$true}
 }
 $out = Join-Path $buildRoot 'final-with-videos.pptx'
 $deck.SaveAs($out,24)
 $receipt = @{slides=$deck.Slides.Count;videos=$entries;file=$out;playback_checks=@();current_media_index=$spec.current_media_index}
 if ($VerifyPlayback) {
  $deck.SlideShowSettings.ShowType = 2
  $deck.SlideShowSettings.ShowWithAnimation = -1
  $window = $deck.SlideShowSettings.Run()
  try {
   foreach ($video in $entries) {
    $window.View.GotoSlide([int]$video.slide)
    Start-Sleep -Milliseconds 700
    $player = $window.View.Player([int]$video.shape_id)
    $player.Play()
    $before = [double]$player.CurrentPosition
    Start-Sleep -Milliseconds 1500
    $after = [double]$player.CurrentPosition
    if ($after -le $before) { throw "Video did not advance on slide $($video.slide): $before -> $after" }
    $receipt.playback_checks += @{slide=$video.slide;position_before=$before;position_after=$after;advanced=$true}
    $player.Stop()
   }
  } finally { $window.View.Exit() }
 }
 $receipt | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $buildRoot 'pptx-export.json') -Encoding utf8
 Write-Output "Saved $out with $($entries.Count) embedded demos; playback checks: $($receipt.playback_checks.Count)"
} finally {
 try { if ($null -ne $deck) { $deck.Close() } } catch { if ($_.Exception.Message -notmatch 'Object does not exist') { throw } }
 try { if ($app.Presentations.Count -eq 0) { $app.Quit() } } catch { if ($_.Exception.Message -notmatch 'Object does not exist|RPC server') { throw } }
}