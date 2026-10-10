param([Parameter(Mandatory=$true)][string]$SvgPath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$resolved = (Resolve-Path -LiteralPath $SvgPath).Path
$app = New-Object -ComObject Illustrator.Application
$document = $null
for ($i = 1; $i -le $app.Documents.Count; $i++) {
    $candidate = $app.Documents.Item($i)
    try {
        if ([string]$candidate.FullName -eq $resolved) { $document = $candidate; break }
    } catch { }
}
$reused = $null -ne $document
if (-not $reused) { $document = $app.Open($resolved) }
if ($null -eq $document) { throw 'Illustrator did not open the SVG' }
@{opened=$true; path=$resolved; reused=$reused} | ConvertTo-Json -Compress
