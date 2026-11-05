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

    [string]$RemoteCrlPath = '/etc/nginx/mtls/client-ca.crl.pem',
    [string]$RemoteCaPath = '/etc/nginx/mtls/client-ca-chain.pem',
    [string]$AdminUrl = 'https://admin.poweradapter.xyz/super_admin/',
    [string]$ClientCertificateSubject = 'O=PowerAdapter, CN=PowerAdapter-Windows-Admin',
    [ValidateRange(1, 168)]
    [int]$RenewBeforeHours = 72,
    [switch]$CheckOnly,
    [switch]$Scheduled,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Status {
    param([string]$Message)

    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Write-Host "[$timestamp] $Message"
}

function Assert-LastExitCode {
    param([string]$Operation)

    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed with exit code $LASTEXITCODE."
    }
}

function Assert-FileExists {
    param([string]$Path, [string]$Description)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description not found: $Path"
    }
}

function Get-CrlUpdateUtc {
    param([string]$CrlPath, [ValidateSet('lastupdate', 'nextupdate')][string]$Field)

    $line = & $OpenSslPath crl -in $CrlPath -noout "-$Field"
    Assert-LastExitCode "Reading the CRL $Field"
    $value = (([string]($line | Select-Object -First 1)) -replace '^[^=]+=', '') -replace '\s+', ' '
    $value = $value.Trim()
    return [DateTime]::ParseExact(
        $value,
        "MMM d HH:mm:ss yyyy 'GMT'",
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::AssumeUniversal -bor
            [Globalization.DateTimeStyles]::AdjustToUniversal
    )
}

function Invoke-Native {
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [string]$Operation
    )

    & $Executable @Arguments
    Assert-LastExitCode $Operation
}

$CaDirectory = [IO.Path]::GetFullPath($CaDirectory)
$OpenSslPath = [IO.Path]::GetFullPath($OpenSslPath)
$SshKeyPath = [IO.Path]::GetFullPath($SshKeyPath)

$caCertificatePath = Join-Path $CaDirectory 'ca.crt.pem'
$caPrivateKeyPath = Join-Path $CaDirectory 'private\ca.key.pem'
$caConfigPath = Join-Path $CaDirectory 'openssl-client-ca.cnf'
$currentCrlPath = Join-Path $CaDirectory 'client-ca.crl.pem'
$logDirectory = Join-Path $CaDirectory 'logs'
$logPath = Join-Path $logDirectory 'crl-renewal.log'

Assert-FileExists $OpenSslPath 'OpenSSL executable'
Assert-FileExists $SshKeyPath 'SSH private key'
Assert-FileExists $caCertificatePath 'Client CA certificate'
Assert-FileExists $caPrivateKeyPath 'Client CA private key'
Assert-FileExists $caConfigPath 'OpenSSL CA configuration'
Assert-FileExists $currentCrlPath 'Current CRL'

if ($SshTarget -notmatch '^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+$') {
    throw "Invalid SSH target: $SshTarget"
}
foreach ($remotePath in @($RemoteCrlPath, $RemoteCaPath)) {
    if ($remotePath -notmatch '^/[A-Za-z0-9._/-]+$') {
        throw "Invalid remote path: $remotePath"
    }
}

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$version = & $OpenSslPath version
Assert-LastExitCode 'Reading the OpenSSL version'
if ([string]$version -notmatch '^OpenSSL 4\.') {
    throw "CRL generation requires OpenSSL 4.x; found: $version"
}

$nextUpdateUtc = Get-CrlUpdateUtc $currentCrlPath 'nextupdate'
$remaining = $nextUpdateUtc - [DateTime]::UtcNow
$isDue = $remaining.TotalHours -le $RenewBeforeHours
$status = "CRL expires at $($nextUpdateUtc.ToString('u')); remaining hours: $([Math]::Round($remaining.TotalHours, 1))."
Write-Status $status
Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) CHECK $status"

if ($CheckOnly) {
    if ($isDue) {
        exit 2
    }
    exit 0
}

if ($Scheduled) {
    if (-not $isDue) {
        exit 0
    }

    $powershellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $launchArguments = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-NoExit',
        '-File', "`"$PSCommandPath`"",
        '-CaDirectory', "`"$CaDirectory`"",
        '-OpenSslPath', "`"$OpenSslPath`"",
        '-SshTarget', "`"$SshTarget`"",
        '-SshKeyPath', "`"$SshKeyPath`"",
        '-RemoteCrlPath', "`"$RemoteCrlPath`"",
        '-RemoteCaPath', "`"$RemoteCaPath`"",
        '-AdminUrl', "`"$AdminUrl`"",
        '-ClientCertificateSubject', "`"$ClientCertificateSubject`"",
        '-RenewBeforeHours', [string]$RenewBeforeHours,
        '-Force'
    ) -join ' '
    Start-Process -FilePath $powershellPath -ArgumentList $launchArguments -WindowStyle Normal
    Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) PROMPT Launched interactive renewal."
    exit 0
}

if (-not $Force -and -not $isDue) {
    Write-Status 'Renewal is not due. Use -Force to renew now.'
    exit 0
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDirectory = Join-Path $CaDirectory "backups\crl-refresh-$stamp"
$pendingCrlPath = Join-Path $CaDirectory "client-ca.crl.pem.pending-$stamp"
New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null

foreach ($name in @('client-ca.crl.pem', 'crlnumber', 'crlnumber.old', 'index.txt', 'index.txt.attr')) {
    $sourcePath = Join-Path $CaDirectory $name
    if (Test-Path -LiteralPath $sourcePath -PathType Leaf) {
        Copy-Item -LiteralPath $sourcePath -Destination $backupDirectory
    }
}
Write-Status "Local CA state backed up to $backupDirectory"

$env:PA_CLIENT_CA_DIR = $CaDirectory
Write-Status 'Generating the CRL. Enter the encrypted Client CA private-key passphrase when prompted.'
Invoke-Native $OpenSslPath @('ca', '-config', $caConfigPath, '-gencrl', '-out', $pendingCrlPath) 'Generating the CRL'
Invoke-Native $OpenSslPath @('crl', '-in', $pendingCrlPath, '-noout', '-verify', '-CAfile', $caCertificatePath) 'Verifying the new CRL signature'
Invoke-Native $OpenSslPath @('crl', '-in', $pendingCrlPath, '-noout', '-issuer', '-lastupdate', '-nextupdate', '-crlnumber') 'Inspecting the new CRL'

$remoteTemporaryPath = "/tmp/poweradapter-client-ca.crl.$stamp.pem"
$sshOptions = @('-i', $SshKeyPath, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes')
Invoke-Native 'scp.exe' ($sshOptions + @($pendingCrlPath, "${SshTarget}:$remoteTemporaryPath")) 'Uploading the new CRL'

$verifyCommand = "sudo -n openssl crl -in $remoteTemporaryPath -noout -verify -CAfile $RemoteCaPath"
Invoke-Native 'ssh.exe' ($sshOptions + @($SshTarget, $verifyCommand)) 'Verifying the uploaded CRL'

# OpenSSL sets lastUpdate to the signing machine's clock. A slower server
# rejects that CRL as "not yet valid" until its own clock reaches lastUpdate.
$validFromUnix = ([DateTimeOffset](Get-CrlUpdateUtc $pendingCrlPath 'lastupdate')).ToUnixTimeSeconds()
$remoteClockReady = $false
for ($attempt = 0; $attempt -lt 24; $attempt++) {
    $remoteTimeText = & ssh.exe @sshOptions $SshTarget 'date -u +%s'
    Assert-LastExitCode 'Reading the server clock'
    $remoteTimeUnix = [long]::Parse(([string]($remoteTimeText | Select-Object -First 1)).Trim())
    if ($remoteTimeUnix -ge ($validFromUnix + 5)) {
        $remoteClockReady = $true
        break
    }
    if ($attempt -eq 0) {
        Write-Status 'Waiting for the server clock to reach the new CRL lastUpdate before deployment.'
    }
    Start-Sleep -Seconds 5
}
if (-not $remoteClockReady) {
    throw 'Server clock is still behind the new CRL lastUpdate after two minutes; the live CRL was not changed.'
}

$remoteBackupPath = "$RemoteCrlPath.bak-$stamp"
$remotePendingPath = "$RemoteCrlPath.pending"
$deployCommand = @(
    'set -eu',
    "sudo -n cp -p $RemoteCrlPath $remoteBackupPath",
    "sudo -n install -o root -g root -m 0644 $remoteTemporaryPath $remotePendingPath",
    "sudo -n mv $remotePendingPath $RemoteCrlPath",
    "if ! sudo -n nginx -t; then sudo -n cp -p $remoteBackupPath $RemoteCrlPath; exit 1; fi",
    "if ! sudo -n systemctl reload nginx; then sudo -n cp -p $remoteBackupPath $RemoteCrlPath; sudo -n nginx -t; sudo -n systemctl reload nginx; exit 1; fi",
    'sudo -n systemctl is-active --quiet nginx',
    "sudo -n rm -f $remoteTemporaryPath"
) -join '; '
Invoke-Native 'ssh.exe' ($sshOptions + @($SshTarget, $deployCommand)) 'Deploying the CRL and reloading Nginx'

Copy-Item -LiteralPath $pendingCrlPath -Destination $currentCrlPath -Force
Remove-Item -LiteralPath $pendingCrlPath

$matchingCertificates = @(Get-ChildItem Cert:\CurrentUser\My | Where-Object {
    $_.Subject -eq $ClientCertificateSubject -and $_.HasPrivateKey
})
if ($matchingCertificates.Count -ne 1) {
    throw "Expected one client certificate for '$ClientCertificateSubject'; found $($matchingCertificates.Count)."
}

$certificateReference = "CurrentUser\MY\$($matchingCertificates[0].Thumbprint)"
$withCertificateStatus = & curl.exe -sS -o NUL -w '%{http_code}' --max-time 20 --cert $certificateReference $AdminUrl
Assert-LastExitCode 'Testing access with the client certificate'
if ($withCertificateStatus -notin @('200', '302')) {
    throw "Client-certificate smoke test returned HTTP $withCertificateStatus."
}

$withoutCertificateStatus = & curl.exe -sS -o NUL -w '%{http_code}' --max-time 20 $AdminUrl
Assert-LastExitCode 'Testing access without a client certificate'
if ($withoutCertificateStatus -ne '400') {
    throw "No-certificate smoke test returned HTTP $withoutCertificateStatus instead of 400."
}

$newNextUpdateUtc = Get-CrlUpdateUtc $currentCrlPath 'nextupdate'
$result = "Renewal complete. Client certificate HTTP $withCertificateStatus; no certificate HTTP $withoutCertificateStatus; next update $($newNextUpdateUtc.ToString('u'))."
Write-Status $result
Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) SUCCESS $result"
