param([Parameter(Mandatory=$true)][string]$Python)
$ErrorActionPreference='Stop'
$pythonPath=(Resolve-Path -LiteralPath $Python).Path
$recoveryScript=Join-Path $PSScriptRoot 'recover.ps1'
$user=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$shellPath=Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
$argsLine='-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$recoveryScript+'" -Python "'+$pythonPath+'"'
$action=New-ScheduledTaskAction -Execute $shellPath -Argument $argsLine
$login=New-ScheduledTaskTrigger -AtLogOn -User $user
$retry=New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 1)
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
Register-ScheduledTask -TaskName 'CellCnsFig2_Client_Recovery' -Action $action -Trigger @($login,$retry) -Principal $principal -Settings $settings -Description 'Restarts explicitly submitted cell_cns_fig2 Python receivers; no new paid submissions or new chats.' -Force | Out-Null
