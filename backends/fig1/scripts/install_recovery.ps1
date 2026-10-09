param([Parameter(Mandatory=$true)][string]$Python)
$ErrorActionPreference='Stop'
$pythonPath=(Resolve-Path -LiteralPath $Python).Path
$pythonWindowless=Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonWindowless -PathType Leaf)) {
    throw 'pythonw.exe is required for windowless resident monitoring.'
}
$monitorScript=Join-Path $PSScriptRoot 'recovery_monitor.py'
$user=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$argsLine='-X utf8 "'+$monitorScript+'"'
$action=New-ScheduledTaskAction -Execute $pythonWindowless -Argument $argsLine
$login=New-ScheduledTaskTrigger -AtLogOn -User $user
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$taskName='CellCnsFig1_Client_Recovery'
# Replaces the former every-minute PowerShell trigger; waiting workers remain untouched.
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $login -Principal $principal -Settings $settings -Description 'Resident windowless Python monitor for existing figure orders; no periodic console launches.' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
