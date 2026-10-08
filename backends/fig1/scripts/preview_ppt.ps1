param([Parameter(Mandatory=$true)][string]$InputPptx,[Parameter(Mandatory=$true)][string]$OutputPng)
$ErrorActionPreference='Stop'
$inputPath=(Resolve-Path -LiteralPath $InputPptx).Path
$app=New-Object -ComObject PowerPoint.Application
$deck=$null
for($i=1;$i -le $app.Presentations.Count;$i++) {
    $candidate=$app.Presentations.Item($i)
    if($candidate.FullName -eq $inputPath) { $deck=$candidate; break }
}
if(-not $deck) { $deck=$app.Presentations.Open($inputPath,-1,0,-1) }
$height=[Math]::Max(1,[Math]::Round(1600*$deck.PageSetup.SlideHeight/$deck.PageSetup.SlideWidth))
$deck.Slides.Item(1).Export([IO.Path]::GetFullPath($OutputPng),'PNG',1600,$height)
# Do not close or modify user presentations, including this isolated output deck.
