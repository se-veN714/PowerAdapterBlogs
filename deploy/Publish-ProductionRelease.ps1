[CmdletBinding()]
param(
    [string]$SshKey = "D:\Work\Project\sec\codex_blog.pem",
    [string]$SshTarget = "ubuntu@42.192.115.111",
    [string]$RemoteRoot = "/opt/blog",
    [switch]$LocalOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}
$manifest = Join-Path $repoRoot "deploy\production-manifest.json"
$archive = Join-Path $env:TEMP "poweradapter-runtime-release.tar.gz"
$ssh = "C:\Windows\System32\OpenSSH\ssh.exe"
$scp = "C:\Windows\System32\OpenSSH\scp.exe"

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $File $($Arguments -join ' ')"
    }
}

Push-Location $repoRoot
try {
    Invoke-Native $python @("deploy\manifest.py", "generate", "--root", ".", "--output", $manifest)
    Invoke-Native $python @("deploy\manifest.py", "verify", "--root", ".", "--manifest", $manifest)
    Invoke-Native $python @("deploy\build_release_archive.py", "--root", ".", "--manifest", $manifest, "--output", $archive)

    if ($LocalOnly) {
        Write-Host "Local release validation completed: $archive"
        return
    }

    if (-not (Test-Path -LiteralPath $SshKey)) {
        throw "SSH key not found: $SshKey"
    }
    Invoke-Native $scp @("-i", $SshKey, $archive, "$SshTarget`:/home/ubuntu/poweradapter-runtime-release.tar.gz")
    $remoteCommand = "sudo tar --no-same-owner -xzf /home/ubuntu/poweradapter-runtime-release.tar.gz -C $RemoteRoot; cd $RemoteRoot; sudo docker compose --env-file deploy/.env.production -f compose.production.yml up -d --build web"
    Invoke-Native $ssh @("-i", $SshKey, $SshTarget, $remoteCommand)
    Write-Host "Production release completed. prepare performed manifest verification before web startup."
}
finally {
    Pop-Location
}
