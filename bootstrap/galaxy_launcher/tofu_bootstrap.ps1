<#
GALAXY exact-challenge TOFU installer.

This script can install only generation 1 in the inactive state.  It has no
controller activation operation and never reads or imports code from the target
checkout.  Its production invocation must be the proposal-bound staging copy,
started elevated by the operator after an exact fresh response is available.
#>
[CmdletBinding(DefaultParameterSetName = 'None')]
param(
    [Parameter(ParameterSetName = 'Path', Mandatory = $true)]
    [string] $SelfTestCanonicalPath,
    [Parameter(ParameterSetName = 'Activation', Mandatory = $true)]
    [switch] $SelfTestFinalActivationSnippet,
    [Parameter(ParameterSetName = 'Singleton', Mandatory = $true)]
    [switch] $SelfTestSingletonLeafSelection,
    [Parameter(ParameterSetName = 'ServiceQuery', Mandatory = $true)]
    [switch] $SelfTestMissingServiceQuery,
    [Parameter(ParameterSetName = 'AnchorTaskContract', Mandatory = $true)]
    [switch] $SelfTestAnchorTaskContract,
    [Parameter(ParameterSetName = 'Install', Mandatory = $true)]
    [string] $ProposalPath,
    [Parameter(ParameterSetName = 'Install', Mandatory = $true)]
    [string] $ResponsePath,
    [Parameter(ParameterSetName = 'Install', Mandatory = $true)]
    [switch] $InstallInactive
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function ConvertTo-CanonicalDrivePath {
    param([Parameter(Mandatory = $true)][string] $Value)
    if ([string]::IsNullOrWhiteSpace($Value) -or
            $Value.StartsWith('\\') -or $Value.StartsWith('//') -or
            $Value.StartsWith('\') -or
            -not [System.Text.RegularExpressions.Regex]::IsMatch(
                $Value, '\A[A-Za-z]:[\\/](?![\\/])')) {
        throw 'only absolute local drive paths are accepted'
    }
    $normalized = $Value.Replace('/', '\')
    if ($normalized.StartsWith('\\?\') -or $normalized.StartsWith('\\.\')) {
        throw 'device and extended paths are forbidden'
    }
    $full = [System.IO.Path]::GetFullPath($normalized)
    if (-not [System.Text.RegularExpressions.Regex]::IsMatch(
            $full, '\A[A-Za-z]:\\(?!\\)')) {
        throw 'canonical path is not an ordinary local drive path'
    }
    return $full.TrimEnd('\')
}

function Assert-NoReparsePath {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $Label
    )
    $full = ConvertTo-CanonicalDrivePath $Path
    $root = [System.IO.Path]::GetPathRoot($full)
    $relative = $full.Substring($root.Length)
    $current = $root.TrimEnd('\')
    foreach ($component in $relative.Split([char]'\')) {
        if ($component.Length -eq 0) { continue }
        $current = [System.IO.Path]::Combine($current, $component)
        if ([System.IO.File]::Exists($current) -or [System.IO.Directory]::Exists($current)) {
            $attributes = [System.IO.File]::GetAttributes($current)
            if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label traverses a reparse point"
            }
        }
    }
    return $full
}

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][string] $Path)
    $stream = New-Object System.IO.FileStream(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = $sha.ComputeHash($stream)
        return ([System.BitConverter]::ToString($digest)).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function Get-Sha256BytesHex {
    param([Parameter(Mandatory = $true)][byte[]] $Bytes)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString(
            $sha.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Assert-PinnedHostSignature {
    param([Parameter(Mandatory = $true)] $Proposal)
    $host = Assert-NoReparsePath -Path ([string]$Proposal.host_path) `
        -Label 'pinned PowerShell host'
    $actualHost = Assert-NoReparsePath -Path (
        [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName) `
        -Label 'running PowerShell host'
    if (-not $actualHost.Equals(
            $host, [System.StringComparison]::OrdinalIgnoreCase) -or
            (Get-Sha256Hex $actualHost) -cne [string]$Proposal.host_sha256) {
        throw 'running PowerShell host differs from the proposal binding'
    }
    $hostSuffix = '\System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not $actualHost.EndsWith(
            $hostSuffix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'running PowerShell host is outside the pinned Windows location'
    }
    $windowsRoot = $actualHost.Substring(0, $actualHost.Length - $hostSuffix.Length)
    $systemModuleRoot = [System.IO.Path]::Combine(
        $windowsRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'Modules')
    [System.Environment]::SetEnvironmentVariable(
        'PSModulePath', $systemModuleRoot,
        [System.EnvironmentVariableTarget]::Process)
    $signature = Microsoft.PowerShell.Security\Get-AuthenticodeSignature `
        -LiteralPath $actualHost -ErrorAction Stop
    if ($null -eq $signature -or $null -eq $signature.SignerCertificate) {
        throw 'PowerShell host signer is unavailable'
    }
    $record = [ordered]@{
        is_os_binary = [bool]$signature.IsOSBinary
        signature_type = [string]$signature.SignatureType
        signer_subject = [string]$signature.SignerCertificate.Subject
        signer_thumbprint = (
            [string]$signature.SignerCertificate.Thumbprint).ToLowerInvariant()
        status = [string]$signature.Status
    }
    $expected = $Proposal.host_signature
    $expectedNames = @($expected.PSObject.Properties.Name)
    if ($expectedNames.Count -ne $record.Count) {
        throw 'PowerShell host signature proposal fields drifted'
    }
    foreach ($name in $record.Keys) {
        if ($name -notin $expectedNames -or
                [string]$record[$name] -cne [string]$expected.$name) {
            throw 'PowerShell host signature differs from the proposal binding'
        }
    }
    if ($record.status -cne 'Valid' -or -not $record.is_os_binary -or
            $record.signature_type -notin @('Catalog', 'Authenticode') -or
            -not $record.signer_subject.StartsWith(
                'CN=Microsoft Windows,', [System.StringComparison]::Ordinal) -or
            -not [System.Text.RegularExpressions.Regex]::IsMatch(
                $record.signer_thumbprint, '\A[0-9a-f]{40}\z')) {
        throw 'PowerShell host signature is not valid and OS-owned'
    }
    $recordBytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes(
        ($record | ConvertTo-Json -Compress))
    if ((Get-Sha256BytesHex $recordBytes) -cne
            [string]$Proposal.host_signature_sha256) {
        throw 'PowerShell host signature record digest drift'
    }
}

function Assert-ExactFile {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][long] $Size,
        [Parameter(Mandatory = $true)][string] $Sha256,
        [Parameter(Mandatory = $true)][string] $Label
    )
    $full = Assert-NoReparsePath -Path $Path -Label $Label
    if (-not [System.IO.File]::Exists($full)) { throw "$Label is unavailable" }
    $info = New-Object System.IO.FileInfo($full)
    if ($info.Length -ne $Size -or (Get-Sha256Hex $full) -cne $Sha256) {
        throw "$Label digest or size drift"
    }
    return $full
}

function ConvertTo-NativeArgument {
    param([Parameter(Mandatory = $true)][string] $Value)
    if ($Value.IndexOf([char]0) -ge 0 -or $Value.Contains('"') -or
            $Value.Contains("`r") -or $Value.Contains("`n")) {
        throw 'native argument contains a forbidden character'
    }
    if ($Value -match '\s') { return '"' + $Value + '"' }
    return $Value
}

function Invoke-ClosedProcess {
    param(
        [Parameter(Mandatory = $true)][string] $Executable,
        [Parameter(Mandatory = $true)][string[]] $Arguments,
        [Parameter(Mandatory = $true)][string] $WorkingDirectory,
        [int] $ExpectedExitCode = 0
    )
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $Executable
    $start.Arguments = (($Arguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' ')
    $start.WorkingDirectory = $WorkingDirectory
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.EnvironmentVariables.Clear()
    $start.EnvironmentVariables['SystemRoot'] = $env:SystemRoot
    $start.EnvironmentVariables['WINDIR'] = $env:SystemRoot
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    if (-not $process.Start()) { throw 'closed child process did not start' }
    $process.StandardInput.Close()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    if (-not $process.WaitForExit(300000)) {
        $process.Kill()
        throw 'closed child process timed out'
    }
    $exitCode = $process.ExitCode
    $process.Dispose()
    if ($exitCode -ne $ExpectedExitCode) {
        throw "closed child process refused ($exitCode): $stderr"
    }
    return $stdout
}

function Assert-ElevatedAdministrator {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole(
            [System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'TOFU installation requires an elevated administrator token'
    }
}

function Get-ExactProposalLeaf {
    param(
        [Parameter(Mandatory = $true)][object[]] $Leaves,
        [Parameter(Mandatory = $true)][string] $LogicalPath
    )
    $matches = @($Leaves | Where-Object { $_.logical_path -ceq $LogicalPath })
    if ($matches.Count -ne 1) {
        throw "proposal leaf is absent or ambiguous: $LogicalPath"
    }
    return $matches[0]
}

function Set-ProtectedStagingClosure {
    param([Parameter(Mandatory = $true)][string] $Root)
    $administrators = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
    $system = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')
    $operator = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    $deny = [System.Security.AccessControl.AccessControlType]::Deny
    $propagation = [System.Security.AccessControl.PropagationFlags]::None
    $directories = New-Object System.Collections.Generic.List[string]
    $files = New-Object System.Collections.Generic.List[string]
    $pending = New-Object System.Collections.Generic.Stack[string]
    $pending.Push($Root)
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        [void]$directories.Add($directory)
        foreach ($entry in [System.IO.Directory]::EnumerateFileSystemEntries($directory)) {
            $attributes = [System.IO.File]::GetAttributes($entry)
            if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'TOFU staging closure contains a reparse point'
            }
            if (($attributes -band [System.IO.FileAttributes]::Directory) -ne 0) {
                $pending.Push($entry)
            }
            else {
                [void]$files.Add($entry)
            }
        }
    }
    foreach ($file in $files) {
        $security = New-Object System.Security.AccessControl.FileSecurity
        $security.SetAccessRuleProtection($true, $false)
        $security.SetOwner($administrators)
        $security.SetGroup($administrators)
        foreach ($principal in @($system, $administrators)) {
            [void]$security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
                $principal,
                [System.Security.AccessControl.FileSystemRights]::FullControl,
                $allow)))
        }
        [void]$security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $operator,
            [System.Security.AccessControl.FileSystemRights]::Delete,
            $deny)))
        [void]$security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $operator,
            [System.Security.AccessControl.FileSystemRights]::ReadAndExecute,
            $allow)))
        (New-Object System.IO.FileInfo($file)).SetAccessControl($security)
    }
    foreach ($directory in $directories) {
        $security = New-Object System.Security.AccessControl.DirectorySecurity
        $security.SetAccessRuleProtection($true, $false)
        $security.SetOwner($administrators)
        $security.SetGroup($administrators)
        $inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
        foreach ($principal in @($system, $administrators)) {
            [void]$security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
                $principal,
                [System.Security.AccessControl.FileSystemRights]::FullControl,
                $inheritance,
                $propagation,
                $allow)))
        }
        $deleteRights = [System.Security.AccessControl.FileSystemRights]::Delete -bor
            [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles
        [void]$security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $operator,
            $deleteRights,
            $inheritance,
            $propagation,
            $deny)))
        [void]$security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $operator,
            [System.Security.AccessControl.FileSystemRights]::ReadAndExecute,
            $inheritance,
            $propagation,
            $allow)))
        (New-Object System.IO.DirectoryInfo($directory)).SetAccessControl($security)
    }
    $rootSecurity = (New-Object System.IO.DirectoryInfo($Root)).GetAccessControl(
        [System.Security.AccessControl.AccessControlSections]::All)
    if (-not $rootSecurity.AreAccessRulesProtected) {
        throw 'TOFU staging ACL inheritance remained enabled'
    }
    return $operator.Value
}

function Assert-ExactResponse {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $Challenge
    )
    $responseFile = Assert-NoReparsePath -Path $Path -Label 'approval response'
    if (-not [System.IO.File]::Exists($responseFile)) {
        throw 'approval response is unavailable'
    }
    $observed = [System.IO.File]::ReadAllBytes($responseFile)
    $expected = [System.Text.Encoding]::ASCII.GetBytes($Challenge)
    $equal = $observed.Length -eq $expected.Length
    $difference = 0
    $limit = [Math]::Max($observed.Length, $expected.Length)
    for ($index = 0; $index -lt $limit; $index++) {
        $left = if ($index -lt $observed.Length) { $observed[$index] } else { 0 }
        $right = if ($index -lt $expected.Length) { $expected[$index] } else { 0 }
        $difference = $difference -bor ($left -bxor $right)
    }
    if (-not $equal -or $difference -ne 0) {
        throw 'fresh response must equal the exact full challenge with no BOM or newline'
    }
    return $responseFile
}

function Set-ProtectedRootAcl {
    param(
        [Parameter(Mandatory = $true)][string] $Root,
        [Parameter(Mandatory = $true)][string] $OperatorSid,
        [Parameter(Mandatory = $true)][string] $ServiceSid
    )
    $security = New-Object System.Security.AccessControl.DirectorySecurity
    $security.SetAccessRuleProtection($true, $false)
    $administrators = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
    $system = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')
    $service = New-Object System.Security.Principal.SecurityIdentifier($ServiceSid)
    $operator = New-Object System.Security.Principal.SecurityIdentifier($OperatorSid)
    $security.SetOwner($administrators)
    $security.SetGroup($administrators)
    $inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    $propagation = [System.Security.AccessControl.PropagationFlags]::None
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    $deny = [System.Security.AccessControl.AccessControlType]::Deny
    foreach ($principal in @($system, $administrators)) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $principal,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            $propagation,
            $allow
        )
        [void]$security.AddAccessRule($rule)
    }
    $serviceRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $service,
        [System.Security.AccessControl.FileSystemRights]::ReadAndExecute,
        $inheritance,
        $propagation,
        $allow
    )
    [void]$security.AddAccessRule($serviceRule)
    $deleteRights = [System.Security.AccessControl.FileSystemRights]::Delete -bor
        [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles
    $operatorDeny = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $operator,
        $deleteRights,
        $inheritance,
        $propagation,
        $deny
    )
    [void]$security.AddAccessRule($operatorDeny)
    $operatorRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $operator,
        [System.Security.AccessControl.FileSystemRights]::ReadAndExecute,
        $inheritance,
        $propagation,
        $allow
    )
    [void]$security.AddAccessRule($operatorRule)
    $directory = New-Object System.IO.DirectoryInfo($Root)
    $directory.SetAccessControl($security)
    $live = $directory.GetAccessControl([System.Security.AccessControl.AccessControlSections]::All)
    if (-not $live.AreAccessRulesProtected) { throw 'protected root ACL inheritance remained enabled' }
    return $live.GetSecurityDescriptorSddlForm(
        [System.Security.AccessControl.AccessControlSections]::All)
}

function Set-SealedGenerationAcl {
    param(
        [Parameter(Mandatory = $true)][string] $GenerationRoot,
        [Parameter(Mandatory = $true)][string] $OperatorSid,
        [Parameter(Mandatory = $true)][string] $ServiceSid
    )
    $security = New-Object System.Security.AccessControl.DirectorySecurity
    $security.SetAccessRuleProtection($true, $false)
    $administrators = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
    $system = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')
    $service = New-Object System.Security.Principal.SecurityIdentifier($ServiceSid)
    $operator = New-Object System.Security.Principal.SecurityIdentifier($OperatorSid)
    $security.SetOwner($administrators)
    $security.SetGroup($administrators)
    $inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    $propagation = [System.Security.AccessControl.PropagationFlags]::None
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    $deny = [System.Security.AccessControl.AccessControlType]::Deny
    $writeRights = [System.Security.AccessControl.FileSystemRights]::WriteData -bor
        [System.Security.AccessControl.FileSystemRights]::AppendData -bor
        [System.Security.AccessControl.FileSystemRights]::WriteExtendedAttributes -bor
        [System.Security.AccessControl.FileSystemRights]::WriteAttributes -bor
        [System.Security.AccessControl.FileSystemRights]::Delete -bor
        [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
        [System.Security.AccessControl.FileSystemRights]::ChangePermissions -bor
        [System.Security.AccessControl.FileSystemRights]::TakeOwnership
    foreach ($principal in @($system, $service)) {
        [void]$security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $principal, $writeRights, $inheritance, $propagation, $deny)))
        [void]$security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $principal,
            [System.Security.AccessControl.FileSystemRights]::ReadAndExecute,
            $inheritance,
            $propagation,
            $allow)))
    }
    [void]$security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
        $administrators,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        $inheritance,
        $propagation,
        $allow)))
    [void]$security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
        $operator,
        [System.Security.AccessControl.FileSystemRights]::ReadAndExecute,
        $inheritance,
        $propagation,
        $allow)))
    $directory = New-Object System.IO.DirectoryInfo($GenerationRoot)
    $directory.SetAccessControl($security)
    $live = $directory.GetAccessControl([System.Security.AccessControl.AccessControlSections]::All)
    if (-not $live.AreAccessRulesProtected) {
        throw 'sealed generation ACL inheritance remained enabled'
    }
}

function Test-BeneathRoot {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $Root
    )
    $candidate = ConvertTo-CanonicalDrivePath $Path
    $prefix = (ConvertTo-CanonicalDrivePath $Root).TrimEnd('\') + '\'
    return $candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Copy-DeclaredClosure {
    param(
        [Parameter(Mandatory = $true)] $Proposal,
        [Parameter(Mandatory = $true)][string] $Root
    )
    $destinations = @{}
    $leaves = @($Proposal.source_leaves) + @($Proposal.artifact_leaves)
    foreach ($leaf in $leaves) {
        $installed = ConvertTo-CanonicalDrivePath ([string]$leaf.installed_path)
        $key = $installed.ToUpperInvariant()
        if ($destinations.ContainsKey($key)) { throw 'duplicate installed proposal path' }
        $destinations[$key] = $true
        if ($null -eq $leaf.staging_path) {
            [void](Assert-ExactFile -Path $installed -Size ([long]$leaf.size) `
                -Sha256 ([string]$leaf.sha256) -Label ([string]$leaf.logical_path))
            continue
        }
        if (-not (Test-BeneathRoot -Path $installed -Root $Root)) {
            throw 'copied proposal leaf escaped the protected root'
        }
        $source = Assert-ExactFile -Path ([string]$leaf.staging_path) `
            -Size ([long]$leaf.size) -Sha256 ([string]$leaf.sha256) `
            -Label ([string]$leaf.logical_path)
        if ([System.IO.File]::Exists($installed) -or [System.IO.Directory]::Exists($installed)) {
            throw 'installed proposal leaf collided with an existing path'
        }
        [void][System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($installed))
        [System.IO.File]::Copy($source, $installed, $false)
        [void](Assert-ExactFile -Path $installed -Size ([long]$leaf.size) `
            -Sha256 ([string]$leaf.sha256) -Label ([string]$leaf.logical_path))
    }
}

function Invoke-ServiceControl {
    param([Parameter(Mandatory = $true)][string[]] $Arguments)
    $sc = [System.IO.Path]::Combine($env:SystemRoot, 'System32', 'sc.exe')
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $sc
    $start.Arguments = (($Arguments | ForEach-Object {
        ConvertTo-NativeArgument $_
    }) -join ' ')
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.EnvironmentVariables.Clear()
    $start.EnvironmentVariables['SystemRoot'] = $env:SystemRoot
    $start.EnvironmentVariables['WINDIR'] = $env:SystemRoot
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    if (-not $process.Start()) { throw 'service control process did not start' }
    $process.StandardInput.Close()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    if (-not $process.WaitForExit(30000)) {
        $process.Kill()
        throw 'service control process timed out'
    }
    $exitCode = $process.ExitCode
    $process.Dispose()
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $stdout + $stderr
    }
}

function Wait-ServiceState {
    param(
        [Parameter(Mandatory = $true)][string] $Name,
        [Parameter(Mandatory = $true)][int] $State
    )
    for ($attempt = 0; $attempt -lt 100; $attempt++) {
        $query = Invoke-ServiceControl @('query', $Name)
        if ($query.ExitCode -eq 0 -and
                $query.Output -match ('STATE\s*:\s*' + $State + '\s')) { return }
        [System.Threading.Thread]::Sleep(100)
    }
    throw "service $Name did not reach state $State"
}

function Register-InactiveService {
    param(
        [Parameter(Mandatory = $true)] $Proposal
    )
    $name = [string]$Proposal.service_name
    $query = Invoke-ServiceControl @('query', $name)
    if ($query.ExitCode -eq 0) { throw 'Singularity service already exists' }
    if ($query.Output -notmatch '1060') { throw 'Singularity service existence is indeterminate' }
    $interpreter = [string]$Proposal.interpreter_path
    $serviceHost = [string]$Proposal.service_host_path
    $binaryPath = '"' + $interpreter + '" -I -S -B "' + $serviceHost + '" --service'
    $created = Invoke-ServiceControl @(
        'create', $name, 'binPath=', $binaryPath,
        'start=', 'demand', 'obj=', 'LocalSystem',
        'DisplayName=', '9to5 Singularity (inactive)'
    )
    if ($created.ExitCode -ne 0) { throw "service creation failed: $($created.Output)" }
    $sidType = Invoke-ServiceControl @('sidtype', $name, 'restricted')
    if ($sidType.ExitCode -ne 0) { throw "restricted service SID setup failed: $($sidType.Output)" }
    $operatorSid = [string]$Proposal.operator_sid
    $serviceSid = [string]$Proposal.service_sid
    if ($operatorSid -notmatch '^S-1(?:-[0-9]+)+$' -or
            $serviceSid -notmatch '^S-1(?:-[0-9]+)+$') {
        throw 'service DACL principal SID is malformed'
    }
    $serviceSddl = 'D:' +
        '(A;;CCLCSWRPWPDTLOCRRC;;;SY)' +
        '(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)' +
        '(A;;LCRP;;;' + $operatorSid + ')' +
        '(A;;CCLCSWLOCRRC;;;' + $serviceSid + ')'
    $secured = Invoke-ServiceControl @('sdset', $name, $serviceSddl)
    if ($secured.ExitCode -ne 0) { throw "service DACL setup failed: $($secured.Output)" }
    $start = Invoke-ServiceControl @('start', $name)
    if ($start.ExitCode -ne 0) { throw "inactive service rehearsal start failed: $($start.Output)" }
    Wait-ServiceState -Name $name -State 4
    $stop = Invoke-ServiceControl @('stop', $name)
    if ($stop.ExitCode -ne 0) { throw "inactive service rehearsal stop failed: $($stop.Output)" }
    Wait-ServiceState -Name $name -State 1
    $configuration = Invoke-ServiceControl @('qc', $name)
    $sidQuery = Invoke-ServiceControl @('qsidtype', $name)
    $daclQuery = Invoke-ServiceControl @('sdshow', $name)
    if ($configuration.ExitCode -ne 0 -or $configuration.Output -notmatch 'DEMAND_START' -or
            $configuration.Output -notmatch 'LocalSystem' -or
            $sidQuery.ExitCode -ne 0 -or $sidQuery.Output -notmatch 'RESTRICTED') {
        throw 'inactive service launch record did not reread exactly'
    }
    if ($daclQuery.ExitCode -ne 0 -or
            $daclQuery.Output -notmatch [regex]::Escape($operatorSid) -or
            $daclQuery.Output -notmatch [regex]::Escape($serviceSid)) {
        throw 'inactive service DACL did not reread its exact principals'
    }
}

function Get-InactiveAnchorTaskContract {
    return [pscustomobject][ordered]@{
        activation_authority = $false
        anchor_source = 'singularity_anchor.ps1'
        fresh_host_flags = @('-NoLogo', '-NoProfile', '-NonInteractive')
        operator_service_rights = 'query-status+start-only'
        registration_state = 'on_demand_inactive'
        schema = 'galaxy.singularity-anchor-task/v1'
        service_host_role = 'restricted-sid-lifecycle-only'
    }
}

function ConvertTo-TaskXmlText {
    param([Parameter(Mandatory = $true)][string] $Value)
    $escaped = [System.Security.SecurityElement]::Escape($Value)
    if ($null -eq $escaped) { throw 'task XML value could not be escaped' }
    return $escaped
}

function Find-ExactScheduledTask {
    param(
        [Parameter(Mandatory = $true)] $RootFolder,
        [Parameter(Mandatory = $true)][string] $Name
    )
    $matches = @()
    $tasks = $RootFolder.GetTasks(1)
    for ($index = 1; $index -le $tasks.Count; $index++) {
        $candidate = $tasks.Item($index)
        if ([string]$candidate.Name -ceq $Name) { $matches += $candidate }
    }
    if ($matches.Count -gt 1) { throw 'anchor task identity is ambiguous' }
    if ($matches.Count -eq 1) { return $matches[0] }
    return $null
}

function Register-InactiveAnchorTask {
    param([Parameter(Mandatory = $true)] $Proposal)
    $name = [string]$Proposal.anchor_task_name
    $launch = $Proposal.anchor_launch_record
    if ($name -cne '9to5SingularityAnchor' -or
            [string]$launch.schema -cne 'galaxy.singularity-anchor-launch/v1' -or
            [string]$launch.activation_state -cne 'inactive' -or
            [string]$launch.host_path -cne [string]$Proposal.host_path -or
            [string]$launch.host_sha256 -cne [string]$Proposal.host_sha256 -or
            [string]$launch.anchor_path -cne [string]$Proposal.anchor_source_path -or
            [string]$launch.anchor_sha256 -cne [string]$Proposal.anchor_source_sha256) {
        throw 'inactive anchor task proposal binding mismatch'
    }
    $arguments = @($launch.arguments)
    if ($arguments.Count -lt 5 -or
            [string]$arguments[0] -cne '-NoLogo' -or
            [string]$arguments[1] -cne '-NoProfile' -or
            [string]$arguments[2] -cne '-NonInteractive' -or
            [string]$arguments[3] -cne '-File' -or
            [string]$arguments[4] -cne [string]$Proposal.anchor_source_path) {
        throw 'inactive anchor task fresh-host arguments drift'
    }
    $workingDirectory = ConvertTo-CanonicalDrivePath ([string]$launch.working_directory)
    if ([System.IO.File]::Exists($workingDirectory)) {
        throw 'inactive anchor working directory is a file'
    }
    if (-not [System.IO.Directory]::Exists($workingDirectory)) {
        [void][System.IO.Directory]::CreateDirectory($workingDirectory)
    }
    [void](Assert-NoReparsePath -Path $workingDirectory `
        -Label 'inactive anchor working directory')
    if ([System.IO.Directory]::GetFileSystemEntries($workingDirectory).Length -ne 0) {
        throw 'inactive anchor working directory is not empty'
    }

    $hostPath = ConvertTo-TaskXmlText ([string]$Proposal.host_path)
    $argumentLine = (($arguments | ForEach-Object {
        ConvertTo-NativeArgument ([string]$_)
    }) -join ' ')
    $argumentsXml = ConvertTo-TaskXmlText $argumentLine
    $workingDirectoryXml = ConvertTo-TaskXmlText $workingDirectory
    $description = ConvertTo-TaskXmlText `
        '9to5 Singularity native anchor; installed inactive with no triggers.'
    $taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>$description</Description></RegistrationInfo>
  <Principals>
    <Principal id="AnchorPrincipal">
      <UserId>S-1-5-18</UserId>
      <LogonType>ServiceAccount</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="AnchorPrincipal">
    <Exec>
      <Command>$hostPath</Command>
      <Arguments>$argumentsXml</Arguments>
      <WorkingDirectory>$workingDirectoryXml</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
    $scheduler = New-Object -ComObject 'Schedule.Service'
    $scheduler.Connect()
    $rootFolder = $scheduler.GetFolder('\')
    if ($null -ne (Find-ExactScheduledTask -RootFolder $rootFolder -Name $name)) {
        throw 'Singularity anchor task already exists'
    }
    # TASK_CREATE=2 and TASK_LOGON_SERVICE_ACCOUNT=5.  Registration has no
    # triggers and this installer never calls IRegisteredTask.Run().
    $registered = $rootFolder.RegisterTask(
        $name, $taskXml, 2, 'SYSTEM', $null, 5, $null)
    $reread = Find-ExactScheduledTask -RootFolder $rootFolder -Name $name
    if ($null -eq $registered -or $null -eq $reread) {
        throw 'inactive anchor task was not durably registered'
    }
    $definition = $reread.Definition
    if ($definition.Triggers.Count -ne 0 -or $definition.Actions.Count -ne 1) {
        throw 'inactive anchor task gained a trigger or ambiguous action'
    }
    $action = $definition.Actions.Item(1)
    $principal = [string]$definition.Principal.UserId
    if ([string]$action.Path -cne [string]$Proposal.host_path -or
            [string]$action.Arguments -cne $argumentLine -or
            [string]$action.WorkingDirectory -cne $workingDirectory -or
            ($principal -cne 'S-1-5-18' -and
                -not $principal.Equals('SYSTEM', [System.StringComparison]::OrdinalIgnoreCase)) -or
            [int]$definition.Principal.LogonType -ne 5 -or
            -not [bool]$definition.Settings.AllowDemandStart -or
            -not [bool]$definition.Settings.Enabled -or
            [bool]$definition.Settings.RunOnlyIfNetworkAvailable -or
            $reread.GetInstances(0).Count -ne 0) {
        throw 'inactive anchor task did not reread exactly'
    }
}

function Install-ExactInactiveClosure {
    param(
        [Parameter(Mandatory = $true)][string] $Proposal,
        [Parameter(Mandatory = $true)][string] $Response
    )
    Assert-ElevatedAdministrator
    $proposalFile = Assert-NoReparsePath -Path $Proposal -Label 'TOFU proposal'
    if (-not [System.IO.File]::Exists($proposalFile)) { throw 'TOFU proposal is unavailable' }
    $actualStagingRoot = [System.IO.Path]::GetDirectoryName($proposalFile)
    $actualOperatorSid = Set-ProtectedStagingClosure -Root $actualStagingRoot
    $proposalBytes = [System.IO.File]::ReadAllBytes($proposalFile)
    $proposalText = New-Object System.Text.UTF8Encoding($false, $true)
    $proposalObject = $proposalText.GetString($proposalBytes) | ConvertFrom-Json
    if ($proposalObject.schema -cne 'galaxy.trust-on-first-install-proposal/v1' -or
            $proposalObject.status -cne 'ready_for_exact_approval' -or
            [int]$proposalObject.generation -ne 1) {
        throw 'only the first reviewed inactive generation can be installed'
    }
    if ((ConvertTo-CanonicalDrivePath ([string]$proposalObject.staging_root)) -cne
            $actualStagingRoot -or
            [string]$proposalObject.operator_sid -cne $actualOperatorSid) {
        throw 'proposal staging root or operator SID binding mismatch'
    }
    Assert-PinnedHostSignature -Proposal $proposalObject
    $stagePython = Assert-NoReparsePath -Path ([string]$proposalObject.interpreter_staging_path) `
        -Label 'staged interpreter'
    $stageVerifier = Assert-NoReparsePath `
        -Path ([string]$proposalObject.proposal_verifier_staging_path) `
        -Label 'staged proposal verifier'
    $stagingRoot = $actualStagingRoot
    $empty = [System.IO.Path]::Combine($stagingRoot, 'preflight-empty')
    if ([System.IO.File]::Exists($empty)) {
        throw 'preflight empty path is a file'
    }
    if ([System.IO.Directory]::Exists($empty)) {
        [void](Assert-NoReparsePath -Path $empty -Label 'preflight empty directory')
        if ([System.IO.Directory]::GetFileSystemEntries($empty).Length -ne 0) {
            throw 'preflight working directory is not empty'
        }
    }
    else {
        [void][System.IO.Directory]::CreateDirectory($empty)
    }
    $verified = Invoke-ClosedProcess -Executable $stagePython -Arguments @(
        '-I', '-S', '-B', $stageVerifier, '--verify-proposal', $proposalFile
    ) -WorkingDirectory $empty
    if ($verified.Trim() -cne 'TOFU proposal closure verified; no authority granted') {
        throw 'proposal verifier did not produce the exact inactive result'
    }
    $selfLeaf = Get-ExactProposalLeaf -Leaves @($proposalObject.source_leaves) `
        -LogicalPath 'bootstrap/tofu_bootstrap.ps1'
    $selfPath = Assert-NoReparsePath -Path $PSCommandPath -Label 'running TOFU bootstrap'
    if ((ConvertTo-CanonicalDrivePath ([string]$selfLeaf.staging_path)) -cne $selfPath -or
            (Get-Sha256Hex $selfPath) -cne [string]$selfLeaf.sha256) {
        throw 'running TOFU bootstrap differs from the proposal-bound staging copy'
    }
    $responseFile = Assert-ExactResponse -Path $Response `
        -Challenge ([string]$proposalObject.challenge)
    $root = ConvertTo-CanonicalDrivePath ([string]$proposalObject.external_root)
    if ([System.IO.Directory]::Exists($root) -or [System.IO.File]::Exists($root)) {
        throw 'external Singularity root already exists'
    }
    [void][System.IO.Directory]::CreateDirectory($root)
    $daclSddl = Set-ProtectedRootAcl -Root $root `
        -OperatorSid ([string]$proposalObject.operator_sid) `
        -ServiceSid ([string]$proposalObject.service_sid)
    Copy-DeclaredClosure -Proposal $proposalObject -Root $root
    $generationRoot = [System.IO.Path]::GetDirectoryName(
        [System.IO.Path]::GetDirectoryName([string]$proposalObject.service_host_path))
    Set-SealedGenerationAcl -GenerationRoot $generationRoot `
        -OperatorSid ([string]$proposalObject.operator_sid) `
        -ServiceSid ([string]$proposalObject.service_sid)
    Register-InactiveService -Proposal $proposalObject
    Register-InactiveAnchorTask -Proposal $proposalObject
    $installedFinalizer = Get-ExactProposalLeaf -Leaves @($proposalObject.source_leaves) `
        -LogicalPath 'bootstrap/tofu_finalize.py'
    $finalOutput = Invoke-ClosedProcess `
        -Executable ([string]$proposalObject.interpreter_path) `
        -Arguments @(
            '-I', '-S', '-B', [string]$installedFinalizer.installed_path,
            '--proposal', $proposalFile,
            '--response', $responseFile,
            '--dacl-sddl', $daclSddl
        ) -WorkingDirectory $empty
    $result = $finalOutput.Trim() | ConvertFrom-Json
    if ($result.status -cne 'installed_inactive' -or
            $result.activation_authority -ne $false -or
            $result.merkle_root -cne [string]$proposalObject.merkle_root) {
        throw 'TOFU finalizer did not return the exact inactive result'
    }
    $service = Invoke-ServiceControl @('query', [string]$proposalObject.service_name)
    if ($service.ExitCode -ne 0 -or $service.Output -notmatch 'STATE\s*:\s*1\s') {
        throw 'installed Singularity service is not stopped/inactive'
    }
    [System.Console]::Out.WriteLine($finalOutput.Trim())
}

function Test-FinalActivationSnippet {
    $snippet = {
        param($GraphWarrant, $ActivationReceipt)
        if ($null -eq $GraphWarrant -or $null -eq $ActivationReceipt) {
            throw 'ActivationAuthorityUnavailable'
        }
        throw 'Source bootstrap cannot activate a controller generation'
    }
    $refused = $false
    try { & $snippet $null $null }
    catch {
        if ($_.Exception.Message -eq 'ActivationAuthorityUnavailable') { $refused = $true }
    }
    if (-not $refused) { throw 'final activation snippet did not fail closed' }
}

try {
    if ($PSCmdlet.ParameterSetName -eq 'Path') {
        [System.Console]::Out.WriteLine((ConvertTo-CanonicalDrivePath $SelfTestCanonicalPath))
        exit 0
    }
    if ($PSCmdlet.ParameterSetName -eq 'Activation') {
        Test-FinalActivationSnippet
        [System.Console]::Out.WriteLine('fail-closed')
        exit 0
    }
    if ($PSCmdlet.ParameterSetName -eq 'Singleton') {
        $leaf = Get-ExactProposalLeaf -Leaves @(
            [pscustomobject]@{ logical_path = 'bootstrap/tofu_finalize.py' }
        ) -LogicalPath 'bootstrap/tofu_finalize.py'
        [System.Console]::Out.WriteLine([string]$leaf.logical_path)
        exit 0
    }
    if ($PSCmdlet.ParameterSetName -eq 'ServiceQuery') {
        $query = Invoke-ServiceControl @(
            'query', '9to5Singularity__MissingServiceQuery__DoNotCreate')
        if ($query.ExitCode -ne 1060 -or $query.Output -notmatch '1060') {
            throw 'missing-service query did not fail closed with 1060'
        }
        [System.Console]::Out.WriteLine('missing-service-query:1060')
        exit 0
    }
    if ($PSCmdlet.ParameterSetName -eq 'AnchorTaskContract') {
        [System.Console]::Out.WriteLine(
            ((Get-InactiveAnchorTaskContract) | ConvertTo-Json -Compress))
        exit 0
    }
    if ($PSCmdlet.ParameterSetName -eq 'Install' -and $InstallInactive) {
        Install-ExactInactiveClosure -Proposal $ProposalPath -Response $ResponsePath
        exit 0
    }
    throw 'TOFU installation requires the complete exact reviewed proposal protocol'
}
catch {
    [System.Console]::Error.WriteLine('GALAXY TOFU refused: ' + $_.Exception.Message)
    exit 2
}
