<#
GALAXY incomplete first-install recovery.

This operator-only tool can remove one exact proposal-bound generation-1 tree
when TOFU stopped before it created a service or any authority record.  It has
no installation, activation, service-deletion, or arbitrary-path mode.  A
create-only intent is made durable before ACLs change, and a create-only
completion receipt is written only after the root and service are both absent.
#>
[CmdletBinding(DefaultParameterSetName = 'None')]
param(
    [Parameter(ParameterSetName = 'Audit', Mandatory = $true)]
    [switch] $AuditIncompleteFirstInstall,
    [Parameter(ParameterSetName = 'Recover', Mandatory = $true)]
    [switch] $RecoverIncompleteFirstInstall,
    [Parameter(ParameterSetName = 'Audit', Mandatory = $true)]
    [Parameter(ParameterSetName = 'Recover', Mandatory = $true)]
    [string] $ProposalPath,
    [Parameter(ParameterSetName = 'Recover', Mandatory = $true)]
    [string] $ResponsePath,
    [Parameter(ParameterSetName = 'Recover', Mandatory = $true)]
    [string] $RecoveryDirectory
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
    $trimmed = $full.TrimEnd('\')
    if ($trimmed.Length -eq 2) { return $trimmed + '\' }
    return $trimmed
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

function Test-BeneathRoot {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $Root
    )
    $candidate = ConvertTo-CanonicalDrivePath $Path
    $prefix = (ConvertTo-CanonicalDrivePath $Root).TrimEnd('\') + '\'
    return $candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-SameCanonicalPath {
    param(
        [Parameter(Mandatory = $true)][string] $Left,
        [Parameter(Mandatory = $true)][string] $Right
    )
    return (ConvertTo-CanonicalDrivePath $Left).Equals(
        (ConvertTo-CanonicalDrivePath $Right),
        [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-RecoveryEvidencePaths {
    param(
        [Parameter(Mandatory = $true)][string] $ProposalFile,
        [Parameter(Mandatory = $true)][string] $ResponseFile,
        [Parameter(Mandatory = $true)][string] $JournalDirectory,
        [Parameter(Mandatory = $true)][string] $Root
    )
    $proposal = Assert-NoReparsePath -Path $ProposalFile -Label 'TOFU proposal'
    $response = Assert-NoReparsePath -Path $ResponseFile -Label 'approval response'
    $journal = Assert-NoReparsePath -Path $JournalDirectory -Label 'recovery journal'
    $externalRoot = ConvertTo-CanonicalDrivePath $Root
    if (-not [System.IO.Directory]::Exists($journal) -or
            (Test-SameCanonicalPath -Left $journal -Right $externalRoot) -or
            (Test-BeneathRoot -Path $journal -Root $externalRoot) -or
            (Test-BeneathRoot -Path $externalRoot -Root $journal)) {
        throw 'recovery journal must be an existing directory outside the external root'
    }
    foreach ($evidence in @($proposal, $response)) {
        if ((Test-SameCanonicalPath -Left $evidence -Right $externalRoot) -or
                (Test-BeneathRoot -Path $evidence -Root $externalRoot)) {
            throw 'recovery proposal and response must remain outside the external root'
        }
    }
}

function Get-Sha256BytesHex {
    param([Parameter(Mandatory = $true)][byte[]] $Bytes)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace(
            '-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
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
        return ([System.BitConverter]::ToString($sha.ComputeHash($stream))).Replace(
            '-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
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

function Read-Proposal {
    param([Parameter(Mandatory = $true)][string] $Path)
    $proposalFile = Assert-NoReparsePath -Path $Path -Label 'TOFU proposal'
    if (-not [System.IO.File]::Exists($proposalFile)) { throw 'TOFU proposal is unavailable' }
    $encoding = New-Object System.Text.UTF8Encoding($false, $true)
    $proposal = $encoding.GetString([System.IO.File]::ReadAllBytes($proposalFile)) |
        ConvertFrom-Json
    $names = @($proposal.PSObject.Properties.Name)
    foreach ($required in @(
            'schema', 'status', 'generation', 'external_root', 'service_name',
            'service_host_path', 'tofu_receipt_path', 'source_leaves',
            'artifact_leaves')) {
        if ($required -notin $names) { throw "TOFU proposal lacks $required" }
    }
    if ($proposal.schema -cne 'galaxy.trust-on-first-install-proposal/v1' -or
            $proposal.status -cne 'ready_for_exact_approval' -or
            [int]$proposal.generation -ne 1 -or
            [string]$proposal.service_name -cne '9to5Singularity') {
        throw 'only the exact generation-1 Singularity proposal can be recovered'
    }
    return $proposal
}

function Get-DeclaredInventory {
    param(
        [Parameter(Mandatory = $true)] $Proposal,
        [Parameter(Mandatory = $true)][string] $Root
    )
    $paths = @{}
    $logicalPaths = @{}
    $lines = New-Object System.Collections.Generic.List[string]
    $records = New-Object System.Collections.Generic.List[object]
    $leaves = @($Proposal.source_leaves) + @($Proposal.artifact_leaves)
    foreach ($leaf in $leaves) {
        $names = @($leaf.PSObject.Properties.Name)
        foreach ($required in @('logical_path', 'staging_path', 'installed_path', 'size', 'sha256')) {
            if ($required -notin $names) { throw "proposal leaf lacks $required" }
        }
        if ($null -eq $leaf.staging_path) { continue }
        $logical = [string]$leaf.logical_path
        $installed = ConvertTo-CanonicalDrivePath ([string]$leaf.installed_path)
        $size = [long]$leaf.size
        $sha256 = [string]$leaf.sha256
        $segments = @($logical.Split([char]'/'))
        if ([string]::IsNullOrWhiteSpace($logical) -or $logical.Contains('\') -or
                $logical.StartsWith('/') -or $logical -match '[\x00-\x1f\x7f]' -or
                @($segments | Where-Object { $_ -in @('', '.', '..') }).Count -gt 0 -or
                $size -lt 0 -or
                -not [System.Text.RegularExpressions.Regex]::IsMatch(
                    $sha256, '\A[0-9a-f]{64}\z')) {
            throw 'proposal leaf schema is malformed'
        }
        $logicalKey = $logical.ToUpperInvariant()
        if ($logicalPaths.ContainsKey($logicalKey)) {
            throw 'duplicate logical proposal path'
        }
        $logicalPaths[$logicalKey] = $leaf
        if (-not (Test-BeneathRoot -Path $installed -Root $Root)) {
            throw 'proposal leaf escaped the partial external root'
        }
        $key = $installed.ToUpperInvariant()
        if ($paths.ContainsKey($key)) { throw 'duplicate installed proposal path' }
        $paths[$key] = $leaf
        $sizeText = $size.ToString([System.Globalization.CultureInfo]::InvariantCulture)
        [void]$lines.Add($logical + [char]0 + $installed + [char]0 +
            $sizeText + [char]0 + $sha256 + "`n")
        [void]$records.Add([pscustomobject]@{
            LogicalPath = $logical
            InstalledPath = $installed
            Size = $size
            Sha256 = $sha256
        })
    }
    if ($records.Count -eq 0) { throw 'proposal declares no installed recovery leaves' }
    $lineArray = $lines.ToArray()
    [System.Array]::Sort($lineArray, [System.StringComparer]::Ordinal)
    $inventoryBytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes(
        [string]::Concat($lineArray))
    return [pscustomobject]@{
        Paths = $paths
        Records = $records.ToArray()
        Count = $records.Count
        Sha256 = Get-Sha256BytesHex $inventoryBytes
    }
}

function Assert-NoAuthorityRecord {
    param(
        [Parameter(Mandatory = $true)] $Proposal,
        [Parameter(Mandatory = $true)][string] $Root
    )
    $receipt = ConvertTo-CanonicalDrivePath ([string]$Proposal.tofu_receipt_path)
    if (-not (Test-BeneathRoot -Path $receipt -Root $Root)) {
        throw 'TOFU receipt path escaped the partial external root'
    }
    foreach ($path in @(
            $receipt,
            [System.IO.Path]::Combine($Root, 'activation-runtime.json'),
            [System.IO.Path]::Combine($Root, 'tofu'),
            [System.IO.Path]::Combine($Root, 'repositories'))) {
        if ([System.IO.File]::Exists($path) -or [System.IO.Directory]::Exists($path)) {
            throw 'authority record exists; incomplete-install recovery is forbidden'
        }
    }
}

function Get-ExpectedDirectories {
    param(
        [Parameter(Mandatory = $true)][object[]] $Records,
        [Parameter(Mandatory = $true)][string] $Root
    )
    $expected = @{}
    $expected[$Root.ToUpperInvariant()] = $Root
    foreach ($record in $Records) {
        $current = [System.IO.Path]::GetDirectoryName([string]$record.InstalledPath)
        while ($null -ne $current -and
                (Test-BeneathRoot -Path $current -Root $Root)) {
            $expected[$current.ToUpperInvariant()] = $current
            $current = [System.IO.Path]::GetDirectoryName($current)
        }
    }
    return $expected
}

function Get-PartialInstallAudit {
    param([Parameter(Mandatory = $true)] $Proposal)
    $root = Assert-NoReparsePath -Path ([string]$Proposal.external_root) `
        -Label 'partial external root'
    if ([System.IO.File]::Exists($root)) { throw 'partial external root is a file' }
    if (-not [System.IO.Directory]::Exists($root)) {
        throw 'partial external root is unavailable'
    }
    Assert-NoAuthorityRecord -Proposal $Proposal -Root $root
    $inventory = Get-DeclaredInventory -Proposal $Proposal -Root $root
    $expectedDirectories = Get-ExpectedDirectories -Records $inventory.Records -Root $root
    foreach ($record in $inventory.Records) {
        [void](Assert-ExactFile -Path $record.InstalledPath -Size $record.Size `
            -Sha256 $record.Sha256 -Label ([string]$record.LogicalPath))
    }
    $actualFileCount = 0
    $pending = New-Object System.Collections.Generic.Stack[string]
    $pending.Push($root)
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        if (-not $expectedDirectories.ContainsKey($directory.ToUpperInvariant())) {
            throw "undeclared directory in partial external root: $directory"
        }
        foreach ($entry in [System.IO.Directory]::EnumerateFileSystemEntries($directory)) {
            $attributes = [System.IO.File]::GetAttributes($entry)
            if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'partial external root contains a reparse point'
            }
            if (($attributes -band [System.IO.FileAttributes]::Directory) -ne 0) {
                $pending.Push((ConvertTo-CanonicalDrivePath $entry))
            }
            else {
                $file = ConvertTo-CanonicalDrivePath $entry
                if (-not $inventory.Paths.ContainsKey($file.ToUpperInvariant())) {
                    throw "undeclared file in partial external root: $file"
                }
                $actualFileCount += 1
            }
        }
    }
    if ($actualFileCount -ne $inventory.Count) {
        throw 'partial external root file count drift'
    }
    Assert-ServiceAbsent -Name ([string]$Proposal.service_name)
    return [ordered]@{
        schema = 'galaxy.partial-tofu-recovery-audit/v1'
        status = 'verified_incomplete_first_install'
        external_root = $root
        installed_leaf_count = $inventory.Count
        installed_inventory_sha256 = $inventory.Sha256
        service_absent = $true
        authority_records_absent = $true
        activation_authority = $false
    }
}

function ConvertTo-CanonicalJsonBytes {
    param([Parameter(Mandatory = $true)] $Value)
    $json = $Value | ConvertTo-Json -Compress -Depth 12
    return (New-Object System.Text.UTF8Encoding($false)).GetBytes($json)
}

function Test-EqualBytes {
    param(
        [Parameter(Mandatory = $true)][byte[]] $Left,
        [Parameter(Mandatory = $true)][byte[]] $Right
    )
    $difference = $Left.Length -bxor $Right.Length
    $limit = [Math]::Max($Left.Length, $Right.Length)
    for ($index = 0; $index -lt $limit; $index++) {
        $leftByte = if ($index -lt $Left.Length) { $Left[$index] } else { 0 }
        $rightByte = if ($index -lt $Right.Length) { $Right[$index] } else { 0 }
        $difference = $difference -bor ($leftByte -bxor $rightByte)
    }
    return $difference -eq 0
}

function Write-CreateOnlyExactFile {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][byte[]] $Bytes,
        [Parameter(Mandatory = $true)][string] $Label
    )
    $full = Assert-NoReparsePath -Path $Path -Label $Label
    $parent = Assert-NoReparsePath -Path ([System.IO.Path]::GetDirectoryName($full)) `
        -Label "$Label directory"
    if (-not [System.IO.Directory]::Exists($parent)) {
        throw "$Label directory is unavailable"
    }
    if ([System.IO.Directory]::Exists($full)) { throw "$Label path is a directory" }
    if ([System.IO.File]::Exists($full)) {
        if (-not (Test-EqualBytes -Left ([System.IO.File]::ReadAllBytes($full)) -Right $Bytes)) {
            throw "$Label replay bytes differ"
        }
        return $full
    }
    try {
        $stream = New-Object System.IO.FileStream(
            $full,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        try {
            $stream.Write($Bytes, 0, $Bytes.Length)
            $stream.Flush($true)
        }
        finally { $stream.Dispose() }
    }
    catch [System.IO.IOException] {
        if (-not [System.IO.File]::Exists($full) -or
                -not (Test-EqualBytes -Left ([System.IO.File]::ReadAllBytes($full)) -Right $Bytes)) {
            throw "$Label create-only persistence raced or failed"
        }
    }
    if (-not (Test-EqualBytes -Left ([System.IO.File]::ReadAllBytes($full)) -Right $Bytes)) {
        throw "$Label did not reread exactly"
    }
    return $full
}

function Assert-RecoveryReceiptPrecondition {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][byte[]] $ExpectedBytes,
        [Parameter(Mandatory = $true)][bool] $RootExists
    )
    $full = Assert-NoReparsePath -Path $Path -Label 'partial TOFU recovery receipt'
    if ([System.IO.Directory]::Exists($full)) {
        throw 'recovery receipt path is a directory'
    }
    if (-not [System.IO.File]::Exists($full)) { return }
    if (-not (Test-EqualBytes -Left ([System.IO.File]::ReadAllBytes($full)) `
            -Right $ExpectedBytes)) {
        throw 'recovery receipt replay bytes differ'
    }
    if ($RootExists) {
        throw 'recovery receipt exists while the partial external root remains'
    }
}

function Assert-ElevatedAdministrator {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole(
            [System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'partial TOFU recovery requires an elevated administrator token'
    }
}

function Assert-ProtectedAdministratorOwnedDirectory {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $Label
    )
    $directory = New-Object System.IO.DirectoryInfo($Path)
    $security = $directory.GetAccessControl(
        [System.Security.AccessControl.AccessControlSections]::All)
    $owner = $security.GetOwner(
        [System.Security.Principal.SecurityIdentifier]).Value
    if (-not $security.AreAccessRulesProtected -or $owner -cne 'S-1-5-32-544') {
        throw "$Label is not protected and Administrators-owned"
    }
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

function Invoke-ServiceControl {
    param([Parameter(Mandatory = $true)][string[]] $Arguments)
    $sc = [System.IO.Path]::Combine($env:SystemRoot, 'System32', 'sc.exe')
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $sc
    $start.Arguments = (($Arguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' ')
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
    return [pscustomobject]@{ ExitCode = $exitCode; Output = $stdout + $stderr }
}

function Assert-ServiceAbsent {
    param([Parameter(Mandatory = $true)][string] $Name)
    $query = Invoke-ServiceControl @('query', $Name)
    if ($query.ExitCode -ne 1060 -or $query.Output -notmatch '1060') {
        throw 'Singularity service exists or its absence is indeterminate'
    }
}

function Assert-ExactResponse {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $Challenge
    )
    $response = Assert-NoReparsePath -Path $Path -Label 'approval response'
    if (-not [System.IO.File]::Exists($response)) { throw 'approval response is unavailable' }
    $observed = [System.IO.File]::ReadAllBytes($response)
    $expected = [System.Text.Encoding]::ASCII.GetBytes($Challenge)
    if (-not (Test-EqualBytes -Left $observed -Right $expected)) {
        throw 'response must equal the exact old full challenge with no BOM or newline'
    }
    return $response
}

function Assert-ProposalClosure {
    param(
        [Parameter(Mandatory = $true)] $Proposal,
        [Parameter(Mandatory = $true)][string] $ProposalFile
    )
    $names = @($Proposal.PSObject.Properties.Name)
    foreach ($required in @(
            'staging_root', 'interpreter_staging_path',
            'proposal_verifier_staging_path', 'challenge', 'merkle_root')) {
        if ($required -notin $names) { throw "TOFU proposal lacks $required" }
    }
    $stagingRoot = Assert-NoReparsePath -Path ([string]$Proposal.staging_root) `
        -Label 'TOFU staging root'
    if ((ConvertTo-CanonicalDrivePath ([System.IO.Path]::GetDirectoryName($ProposalFile))) -cne
            $stagingRoot) {
        throw 'TOFU proposal staging binding mismatch'
    }
    $empty = Assert-NoReparsePath -Path ([System.IO.Path]::Combine(
            $stagingRoot, 'preflight-empty')) -Label 'preflight empty directory'
    if (-not [System.IO.Directory]::Exists($empty) -or
            [System.IO.Directory]::GetFileSystemEntries($empty).Length -ne 0) {
        throw 'preflight working directory is unavailable or nonempty'
    }
    $python = Assert-NoReparsePath -Path ([string]$Proposal.interpreter_staging_path) `
        -Label 'staged interpreter'
    $verifier = Assert-NoReparsePath `
        -Path ([string]$Proposal.proposal_verifier_staging_path) `
        -Label 'staged proposal verifier'
    $verified = Invoke-ClosedProcess -Executable $python -Arguments @(
        '-I', '-S', '-B', $verifier, '--verify-proposal', $ProposalFile
    ) -WorkingDirectory $empty
    if ($verified.Trim() -cne 'TOFU proposal closure verified; no authority granted') {
        throw 'proposal verifier did not produce the exact inactive result'
    }
}

function Set-AdministratorDeletionAcl {
    param([Parameter(Mandatory = $true)][string] $Root)
    $administrators = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')
    $system = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    $none = [System.Security.AccessControl.PropagationFlags]::None
    $inheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    $files = New-Object System.Collections.Generic.List[string]
    $directories = New-Object System.Collections.Generic.List[string]
    $pending = New-Object System.Collections.Generic.Stack[string]
    $pending.Push($Root)
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        [void]$directories.Add($directory)
        foreach ($entry in [System.IO.Directory]::EnumerateFileSystemEntries($directory)) {
            $attributes = [System.IO.File]::GetAttributes($entry)
            if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'partial external root changed to a reparse point before deletion'
            }
            if (($attributes -band [System.IO.FileAttributes]::Directory) -ne 0) {
                $pending.Push($entry)
            }
            else { [void]$files.Add($entry) }
        }
    }
    foreach ($file in $files) {
        $security = New-Object System.Security.AccessControl.FileSecurity
        $security.SetAccessRuleProtection($true, $false)
        $security.SetOwner($administrators)
        foreach ($principal in @($system, $administrators)) {
            [void]$security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
                $principal,
                [System.Security.AccessControl.FileSystemRights]::FullControl,
                $allow)))
        }
        (New-Object System.IO.FileInfo($file)).SetAccessControl($security)
    }
    $directoryArray = $directories.ToArray()
    [System.Array]::Sort($directoryArray, [System.StringComparer]::OrdinalIgnoreCase)
    [System.Array]::Reverse($directoryArray)
    foreach ($directory in $directoryArray) {
        $security = New-Object System.Security.AccessControl.DirectorySecurity
        $security.SetAccessRuleProtection($true, $false)
        $security.SetOwner($administrators)
        foreach ($principal in @($system, $administrators)) {
            [void]$security.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
                $principal,
                [System.Security.AccessControl.FileSystemRights]::FullControl,
                $inheritance,
                $none,
                $allow)))
        }
        (New-Object System.IO.DirectoryInfo($directory)).SetAccessControl($security)
    }
}

function Recover-IncompleteFirstInstall {
    param(
        [Parameter(Mandatory = $true)][string] $ProposalFile,
        [Parameter(Mandatory = $true)][string] $ResponseFile,
        [Parameter(Mandatory = $true)][string] $JournalDirectory
    )
    Assert-ElevatedAdministrator
    $proposalCanonical = Assert-NoReparsePath -Path $ProposalFile -Label 'TOFU proposal'
    $proposal = Read-Proposal $proposalCanonical
    Assert-ProposalClosure -Proposal $proposal -ProposalFile $proposalCanonical
    $responseCanonical = Assert-ExactResponse -Path $ResponseFile `
        -Challenge ([string]$proposal.challenge)
    Assert-ServiceAbsent -Name ([string]$proposal.service_name)
    $root = ConvertTo-CanonicalDrivePath ([string]$proposal.external_root)
    Assert-RecoveryEvidencePaths -ProposalFile $proposalCanonical `
        -ResponseFile $responseCanonical -JournalDirectory $JournalDirectory -Root $root
    $journal = Assert-NoReparsePath -Path $JournalDirectory -Label 'recovery journal'
    $proposalSha = Get-Sha256Hex $proposalCanonical
    $responseSha = Get-Sha256Hex $responseCanonical
    $inventory = Get-DeclaredInventory -Proposal $proposal -Root $root
    $intent = [ordered]@{
        schema = 'galaxy.partial-tofu-recovery-intent/v1'
        status = 'prepared'
        proposal_sha256 = $proposalSha
        response_sha256 = $responseSha
        merkle_root = [string]$proposal.merkle_root
        external_root = $root
        service_name = [string]$proposal.service_name
        installed_leaf_count = $inventory.Count
        installed_inventory_sha256 = $inventory.Sha256
        service_absent = $true
        authority_records_absent = $true
        activation_authority = $false
    }
    $intentBytes = ConvertTo-CanonicalJsonBytes $intent
    $intentPath = [System.IO.Path]::Combine(
        $journal, "partial-tofu-$proposalSha.intent.json")
    $receiptPath = [System.IO.Path]::Combine(
        $journal, "partial-tofu-$proposalSha.receipt.json")
    $intentExists = [System.IO.File]::Exists($intentPath)
    $rootExists = [System.IO.Directory]::Exists($root)
    if ([System.IO.File]::Exists($root)) { throw 'partial external root is a file' }
    if (-not $rootExists -and -not $intentExists) {
        throw 'partial external root disappeared before a durable recovery intent'
    }
    if ($rootExists) {
        $audit = Get-PartialInstallAudit -Proposal $proposal
        if ($audit.installed_inventory_sha256 -cne $inventory.Sha256) {
            throw 'partial install audit disagrees with proposal inventory'
        }
        Assert-ProtectedAdministratorOwnedDirectory -Path $root -Label 'partial external root'
        $generationRoot = [System.IO.Path]::GetDirectoryName(
            [System.IO.Path]::GetDirectoryName([string]$proposal.service_host_path))
        if (-not (Test-BeneathRoot -Path $generationRoot -Root $root)) {
            throw 'proposal generation root escaped the partial external root'
        }
        Assert-ProtectedAdministratorOwnedDirectory -Path $generationRoot `
            -Label 'partial generation root'
    }
    [void](Write-CreateOnlyExactFile -Path $intentPath -Bytes $intentBytes `
        -Label 'partial TOFU recovery intent')
    $intentSha = Get-Sha256BytesHex $intentBytes
    $receipt = [ordered]@{
        schema = 'galaxy.partial-tofu-recovery-receipt/v1'
        status = 'removed_incomplete_first_install'
        intent_sha256 = $intentSha
        proposal_sha256 = $proposalSha
        merkle_root = [string]$proposal.merkle_root
        external_root = $root
        service_name = [string]$proposal.service_name
        root_absent = $true
        service_absent = $true
        activation_authority = $false
    }
    $receiptBytes = ConvertTo-CanonicalJsonBytes $receipt
    Assert-RecoveryReceiptPrecondition -Path $receiptPath `
        -ExpectedBytes $receiptBytes -RootExists $rootExists
    if ($rootExists) {
        Set-AdministratorDeletionAcl -Root $root
        [System.IO.Directory]::Delete($root, $true)
    }
    if ([System.IO.Directory]::Exists($root) -or [System.IO.File]::Exists($root)) {
        throw 'partial external root remained after exact deletion'
    }
    Assert-ServiceAbsent -Name ([string]$proposal.service_name)
    [void](Write-CreateOnlyExactFile -Path $receiptPath -Bytes $receiptBytes `
        -Label 'partial TOFU recovery receipt')
    [System.Console]::Out.WriteLine((New-Object System.Text.UTF8Encoding(
        $false)).GetString($receiptBytes))
}

try {
    if ($PSCmdlet.ParameterSetName -eq 'Audit' -and $AuditIncompleteFirstInstall) {
        $proposal = Read-Proposal $ProposalPath
        $audit = Get-PartialInstallAudit -Proposal $proposal
        [System.Console]::Out.WriteLine(($audit | ConvertTo-Json -Compress -Depth 12))
        exit 0
    }
    if ($PSCmdlet.ParameterSetName -eq 'Recover' -and $RecoverIncompleteFirstInstall) {
        Recover-IncompleteFirstInstall -ProposalFile $ProposalPath `
            -ResponseFile $ResponsePath -JournalDirectory $RecoveryDirectory
        exit 0
    }
    throw 'recovery requires the complete exact incomplete-first-install protocol'
}
catch {
    [System.Console]::Error.WriteLine(
        'GALAXY partial TOFU recovery refused: ' + $_.Exception.Message)
    exit 2
}
