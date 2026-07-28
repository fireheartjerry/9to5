<#
Portable developer ingress for an already installed Singularity controller.

This file has no launch or activation authority.  It starts only the installed
request client in a fresh Windows PowerShell process.  If that installation is
unavailable or nonordinary, it refuses without consulting the current checkout.
#>
[CmdletBinding(DefaultParameterSetName = 'Request')]
param(
    [Parameter(ParameterSetName = 'Contract', Mandatory = $true)]
    [switch] $SelfTestContract,
    [Parameter(ParameterSetName = 'Request', ValueFromRemainingArguments = $true)]
    [string[]] $RequestArguments
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function ConvertTo-WindowsNativeArgument {
    param([Parameter(Mandatory = $true)][string] $Value)
    if ($Value.IndexOf([char]0) -ge 0 -or $Value.Contains("`r") -or
            $Value.Contains("`n") -or $Value.Length -gt 8192) {
        throw 'request argument is malformed or exceeds the closed limit'
    }
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $builder = [System.Text.StringBuilder]::new()
    [void]$builder.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $slashes += 1
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * (($slashes * 2) + 1)))
            [void]$builder.Append('"')
            $slashes = 0
            continue
        }
        if ($slashes -gt 0) {
            [void]$builder.Append(('\' * $slashes))
            $slashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($slashes -gt 0) { [void]$builder.Append(('\' * ($slashes * 2))) }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Assert-OrdinaryAbsoluteFile {
    param([Parameter(Mandatory = $true)][string] $Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or
            -not [System.IO.Path]::IsPathRooted($Path) -or
            $Path.StartsWith('\\') -or $Path.StartsWith('//')) {
        throw 'installed request client path is not a strict local absolute path'
    }
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($full)
    $current = $root.TrimEnd('\')
    foreach ($component in $full.Substring($root.Length).Split([char]'\')) {
        if ($component.Length -eq 0) { continue }
        $current = [System.IO.Path]::Combine($current, $component)
        if ([System.IO.File]::Exists($current) -or
                [System.IO.Directory]::Exists($current)) {
            $attributes = [System.IO.File]::GetAttributes($current)
            if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'installed request client path traverses a reparse point'
            }
        }
    }
    if (-not [System.IO.File]::Exists($full)) {
        throw 'Singularity request client is not installed'
    }
    return $full
}

if ($SelfTestContract) {
    [System.Console]::Out.Write(
        '{"activation_authority":false,"checkout_fallback":false,' +
        '"client_flags":["--request-only","--require-server-validated-client-digest"],' +
        '"fresh_host_flags":["-NoLogo","-NoProfile","-NonInteractive"],' +
        '"schema":"galaxy.developer-redirect/v1"}'
    )
    exit 0
}

try {
    $localApplicationData = [System.Environment]::GetFolderPath(
        [System.Environment+SpecialFolder]::LocalApplicationData)
    $client = Assert-OrdinaryAbsoluteFile ([System.IO.Path]::Combine(
        $localApplicationData, '9to5', 'singularity', 'bin',
        'singularity-admin-client.ps1'))
    $systemRoot = [System.Environment]::GetEnvironmentVariable(
        'SystemRoot', [System.EnvironmentVariableTarget]::Machine)
    if ([string]::IsNullOrWhiteSpace($systemRoot)) {
        throw 'machine SystemRoot is unavailable'
    }
    $hostPath = Assert-OrdinaryAbsoluteFile ([System.IO.Path]::Combine(
        $systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe'))
    $arguments = [System.Collections.Generic.List[string]]::new()
    foreach ($value in @(
            '-NoLogo', '-NoProfile', '-NonInteractive', '-File', $client,
            '--request-only', '--require-server-validated-client-digest')) {
        [void]$arguments.Add((ConvertTo-WindowsNativeArgument $value))
    }
    foreach ($value in @($RequestArguments)) {
        [void]$arguments.Add((ConvertTo-WindowsNativeArgument $value))
    }
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $hostPath
    $start.Arguments = [string]::Join(' ', $arguments)
    $start.WorkingDirectory = [System.IO.Path]::GetTempPath()
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.EnvironmentVariables.Clear()
    $start.EnvironmentVariables['SystemRoot'] = $systemRoot
    $start.EnvironmentVariables['WINDIR'] = $systemRoot
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $start
    if (-not $process.Start()) { throw 'fresh request client process did not start' }
    $process.StandardInput.Close()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    if (-not $process.WaitForExit(300000)) {
        $process.Kill()
        throw 'request client process timed out'
    }
    $exitCode = $process.ExitCode
    $process.Dispose()
    [System.Console]::Out.Write($stdout)
    [System.Console]::Error.Write($stderr)
    exit $exitCode
}
catch {
    [System.Console]::Error.WriteLine(
        'GALAXY developer redirect refused: ' + $_.Exception.Message)
    exit 78
}
