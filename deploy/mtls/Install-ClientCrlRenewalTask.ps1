[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CaDirectory,

    [Parameter(Mandatory = $true)]
    [string]$OpenSslPath,

    [Parameter(Mandatory = $true)]
    [string]$SshTarget,

    [Parameter(Mandatory = $true)]
    [string]$SshKeyPath,

    [string]$AdminUrl = 'https://admin.poweradapter.xyz/super_admin/',
    [string]$ClientCertificateSubject = 'O=PowerAdapter, CN=PowerAdapter-Windows-Admin',
    [ValidateRange(1, 168)]
    [int]$RenewBeforeHours = 72,
    [ValidateRange(0, 23)]
    [int]$DailyHour = 9,
    [string]$TaskName = 'PowerAdapter Client CRL Renewal'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$refreshScriptPath = Join-Path $PSScriptRoot 'Refresh-ClientCrl.ps1'
if (-not (Test-Path -LiteralPath $refreshScriptPath -PathType Leaf)) {
    throw "Renewal script not found: $refreshScriptPath"
}

$powershellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = @(
    '-NoProfile',
    '-WindowStyle', 'Hidden',
    '-ExecutionPolicy', 'Bypass',
    '-File', "`"$refreshScriptPath`"",
    '-CaDirectory', "`"$CaDirectory`"",
    '-OpenSslPath', "`"$OpenSslPath`"",
    '-SshTarget', "`"$SshTarget`"",
    '-SshKeyPath', "`"$SshKeyPath`"",
    '-AdminUrl', "`"$AdminUrl`"",
    '-ClientCertificateSubject', "`"$ClientCertificateSubject`"",
    '-RenewBeforeHours', [string]$RenewBeforeHours,
    '-Scheduled'
) -join ' '

$action = New-ScheduledTaskAction -Execute $powershellPath -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Daily -At ([DateTime]::Today.AddHours($DailyHour))
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Checks the PowerAdapter client CRL daily and opens an interactive renewal window before expiry.' `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
[pscustomobject]@{
    TaskName = $task.TaskName
    State = $task.State
    DailyHour = $DailyHour
    RenewBeforeHours = $RenewBeforeHours
    RunsOnlyWhenUserIsLoggedOn = $true
}

