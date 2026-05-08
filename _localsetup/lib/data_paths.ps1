# Localsetup v3 - Path resolution (PowerShell)
# Purpose: Repo-local path resolution; mirrors data_paths.sh.
# When deployed, framework is at _localsetup/framework; set LOCALSETUP_PROJECT_ROOT for client repo root.

function Get-UserHome {
    if ($env:USERPROFILE) { return $env:USERPROFILE }
    if ($env:HOME) { return $env:HOME }
    return [Environment]::GetFolderPath('UserProfile')
}

function Get-UserDataDir {
    if ($env:LOCALSETUP_PROJECT_DATA -and (Test-Path -LiteralPath $env:LOCALSETUP_PROJECT_DATA)) {
        return $env:LOCALSETUP_PROJECT_DATA
    }
    if ($env:LOCALSETUP_PROJECT_ROOT) {
        $p = Join-Path $env:LOCALSETUP_PROJECT_ROOT '.localsetup-project'
        if (Test-Path -LiteralPath $p) { return $p }
        return $p
    }
    return (Join-Path (Get-UserHome) '.localsetup')
}

function Get-EngineDir {
    if ($env:LOCALSETUP_FRAMEWORK_DIR -and (Test-Path -LiteralPath $env:LOCALSETUP_FRAMEWORK_DIR)) {
        return $env:LOCALSETUP_FRAMEWORK_DIR
    }
    $engineDir = (Get-Item (Join-Path $PSScriptRoot '..')).FullName
    return $engineDir
}

function Get-ProjectRoot {
    if ($env:LOCALSETUP_PROJECT_ROOT -and (Test-Path -LiteralPath $env:LOCALSETUP_PROJECT_ROOT)) {
        return $env:LOCALSETUP_PROJECT_ROOT
    }
    $engineDir = Get-EngineDir
    $parent = (Get-Item (Join-Path $engineDir '..')).FullName
    $parentName = [System.IO.Path]::GetFileName($parent.TrimEnd([System.IO.Path]::DirectorySeparatorChar))
    if ($parentName -eq '_localsetup') {
        return (Get-Item (Join-Path $parent '..')).FullName
    }
    return $parent
}

function Ensure-UserDataDir {
    $userDataDir = Get-UserDataDir
    $subdirs = @(
        (Join-Path $userDataDir 'context\system'),
        (Join-Path $userDataDir 'context\rules'),
        (Join-Path $userDataDir 'context\research'),
        (Join-Path $userDataDir 'scripts\temp'),
        (Join-Path $userDataDir 'scripts\dry-run'),
        (Join-Path $userDataDir 'scripts\archive'),
        (Join-Path $userDataDir 'logs'),
        (Join-Path $userDataDir 'config')
    )
    foreach ($d in $subdirs) {
        New-Item -ItemType Directory -Force -Path $d | Out-Null
    }
    return $userDataDir
}

function Get-PathSeparator {
    if ($env:OS -eq 'Windows_NT') { return '\' }
    return '/'
}
