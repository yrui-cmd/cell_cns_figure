param(
    [Parameter(Mandatory=$true)][string]$SvgPath,
    [string]$PreviewPath,
    [string]$AiPath,
    [string]$AuditPath
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$resolved = (Resolve-Path -LiteralPath $SvgPath).Path
if (-not $PreviewPath) { $PreviewPath = [IO.Path]::ChangeExtension($resolved, '.illustrator.png') }
$fileJson = $resolved | ConvertTo-Json -Compress
$previewJson = [IO.Path]::GetFullPath($PreviewPath) | ConvertTo-Json -Compress
$aiJson = $AiPath | ConvertTo-Json -Compress
$auditJson = $AuditPath | ConvertTo-Json -Compress
if ($AiPath -and (Test-Path -LiteralPath $AiPath)) { throw 'Refusing to overwrite an existing AI file' }
$app = New-Object -ComObject Illustrator.Application
try {
    $script = @"
(function() {
    var file = new File($fileJson), doc = null, reused = false;
    var before = app.userInteractionLevel;
    try {
        for (var i=0; !$aiJson && i<app.documents.length; i++) {
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
        var mergedTextPaintPairs = 0;
        if ($aiJson) {
            var saveOptions = new IllustratorSaveOptions();
            saveOptions.pdfCompatible = true;
            saveOptions.compressed = true;
            doc.saveAs(new File($aiJson), saveOptions);
            // Verify the saved native document, rather than the in-memory SVG import.
            doc.close(SaveOptions.DONOTSAVECHANGES);
            doc = app.open(new File($aiJson));
            // Illustrator splits a filled-and-stroked SVG text run into two
            // coincident live text frames. Recombine only adjacent matching paint pairs.
            for (var ti=doc.textFrames.length-1;ti>=0;ti--) {
                var st=doc.textFrames[ti], sa=st.textRange.characterAttributes, parent=st.parent;
                if (sa.fillColor.typename!=='NoColor' || sa.strokeColor.typename==='NoColor' ||
                    parent.typename!=='GroupItem' || st.opacity!==100 || st.blendingMode!==BlendModes.NORMAL) continue;
                var ft=null;
                for(var fi=0;fi<parent.pageItems.length-1;fi++) {
                    if(parent.pageItems[fi].uuid===st.uuid) {
                        var candidate=parent.pageItems[fi+1];
                        if(candidate.typename==='TextFrame' && candidate.contents===st.contents) ft=candidate;
                        break;
                    }
                }
                if(!ft || ft.opacity!==100 || ft.blendingMode!==BlendModes.NORMAL) continue;
                var fa=ft.textRange.characterAttributes;
                if(fa.fillColor.typename==='NoColor' || fa.strokeColor.typename!=='NoColor' ||
                    ft.contents!==st.contents || fa.textFont.name!==sa.textFont.name || Math.abs(fa.size-sa.size)>.0001 ||
                    String(ft.position)!==String(st.position) || String(ft.geometricBounds)!==String(st.geometricBounds)) continue;
                fa.strokeColor=sa.strokeColor; fa.strokeWeight=sa.strokeWeight;
                st.remove(); mergedTextPaintPairs++;
            }
            if(mergedTextPaintPairs) {
                doc.save(); doc.close(SaveOptions.DONOTSAVECHANGES);
                doc = app.open(new File($aiJson));
            }
        }
        if ($auditJson) {
            function encode(v) {
                if (v === null) return 'null';
                if (typeof v === 'string') return '"' + v.replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/\r/g,'\\r').replace(/\n/g,'\\n').replace(/\t/g,'\\t').replace(/[\x00-\x1f]/g,function(c){return '\\u'+('0000'+c.charCodeAt(0).toString(16)).slice(-4);}) + '"';
                if (typeof v === 'number' || typeof v === 'boolean') return String(v);
                var a=[], k;
                if (v instanceof Array) { for(k=0;k<v.length;k++) a.push(encode(v[k])); return '['+a.join(',')+']'; }
                for(k in v) if(v.hasOwnProperty(k)) a.push(encode(k)+':'+encode(v[k]));
                return '{'+a.join(',')+'}';
            }
            function numbers(v) { var a=[]; for(var n=0;n<v.length;n++) a.push(Number(v[n])); return a; }
            var texts=[];
            for(var j=0;j<doc.textFrames.length;j++) {
                var t=doc.textFrames[j], chars=t.textRange.characterAttributes;
                texts.push({text:t.contents, position:numbers(t.position), bounds:numbers(t.geometricBounds),
                    font:chars.textFont.name, size:chars.size});
            }
            var audit={paths:doc.pathItems.length, text_frames:doc.textFrames.length, raster_items:doc.rasterItems.length,
                placed_items:doc.placedItems.length, artboard:numbers(doc.artboards[0].artboardRect),
                text:texts, merged_text_paint_pairs:mergedTextPaintPairs, saved_and_reopened:!!$aiJson, version:app.version};
            var af=new File($auditJson); af.encoding='UTF-8';
            if(!af.open('w')) throw new Error('Cannot write Illustrator audit');
            af.write(encode(audit)); af.close();
        }
        var options = new ExportOptionsPNG24();
        options.antiAliasing = true; options.transparency = false;
        options.artBoardClipping = true; options.horizontalScale = 100; options.verticalScale = 100;
        doc.exportFile(new File($previewJson), ExportType.PNG24, options);
        return "OK|" + (reused ? "1" : "0") + "|" + doc.pathItems.length + "|" + doc.textFrames.length + "|" + doc.rasterItems.length;
    } catch(e) {
        return "ERROR|" + e.message + " (line " + e.line + ")";
    } finally { app.userInteractionLevel = before; }
}());
"@
    $result = [string]$app.DoJavaScript($script)
    if (-not $result.StartsWith('OK|')) { throw $result }
    $fields = $result.Split('|')
    if (-not (Test-Path -LiteralPath $PreviewPath -PathType Leaf)) { throw 'Illustrator preview missing' }
    @{opened=$true; path=$resolved; reused=($fields[1] -eq '1'); preview=$PreviewPath;
      paths=[int]$fields[2]; text_frames=[int]$fields[3]; raster_items=[int]$fields[4]; ai=$AiPath; audit=$AuditPath} | ConvertTo-Json -Compress
} finally {
    if ($null -ne $app) { [Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null }
}
