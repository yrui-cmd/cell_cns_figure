param(
    [Parameter(Mandatory=$true)][string]$SvgPath,
    [string]$PreviewPath
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$resolved = (Resolve-Path -LiteralPath $SvgPath).Path
if (-not $PreviewPath) { $PreviewPath = [IO.Path]::ChangeExtension($resolved, '.illustrator.png') }
$fileJson = $resolved | ConvertTo-Json -Compress
$previewJson = [IO.Path]::GetFullPath($PreviewPath) | ConvertTo-Json -Compress
$app = New-Object -ComObject Illustrator.Application
try {
    $script = @"
(function() {
    var file = new File($fileJson), doc = null, reused = false;
    var before = app.userInteractionLevel;
    try {
        for (var i=0; i<app.documents.length; i++) {
            try {
                if (app.documents[i].fullName.fsName.toLowerCase() === file.fsName.toLowerCase()) {
                    doc = app.documents[i]; reused = true; break;
                }
            } catch(e) {}
        }
        // Only this import call suppresses format notices; restore app state in finally.
        // The caller must inspect the actual exported preview before completion.
        app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;
        if (!doc) doc = app.open(file);
        if (!doc) throw new Error("Illustrator did not open the SVG");
        var options = new ExportOptionsPNG24();
        options.antiAliasing = true; options.transparency = false;
        options.artBoardClipping = true; options.horizontalScale = 100; options.verticalScale = 100;
        doc.exportFile(new File($previewJson), ExportType.PNG24, options);
        return "OK|" + (reused ? "1" : "0") + "|" + doc.pathItems.length + "|" + doc.textFrames.length + "|" + doc.rasterItems.length;
    } catch(e) {
        return "ERROR|" + e.message;
    } finally { app.userInteractionLevel = before; }
}());
"@
    $result = [string]$app.DoJavaScript($script)
    if (-not $result.StartsWith('OK|')) { throw $result }
    $fields = $result.Split('|')
    if (-not (Test-Path -LiteralPath $PreviewPath -PathType Leaf)) { throw 'Illustrator preview missing' }
    @{opened=$true; path=$resolved; reused=($fields[1] -eq '1'); preview=$PreviewPath;
      paths=[int]$fields[2]; text_frames=[int]$fields[3]; raster_items=[int]$fields[4]} | ConvertTo-Json -Compress
} finally {
    if ($null -ne $app) { [Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null }
}
