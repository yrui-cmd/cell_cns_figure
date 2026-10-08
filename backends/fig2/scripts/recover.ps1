param([Parameter(Mandatory=$true)][string]$Python)
$ErrorActionPreference='Stop'
& $Python -X utf8 (Join-Path $PSScriptRoot 'client.py') recover | Out-Null
exit $LASTEXITCODE
