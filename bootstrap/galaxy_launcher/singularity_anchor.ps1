<#
GALAXY pre-Python Singularity anchor.

The installed copy is started by a protected fresh-host action.  Before any
interpreter starts, this source verifies its host, its own bytes, the JSON
parser assembly, the protected record, and the inactive/active generation
chain.  The checkout is never a discovery or execution input.
#>
[CmdletBinding(DefaultParameterSetName = 'Run')]
param(
    [Parameter(ParameterSetName = 'Contract', Mandatory = $true)]
    [switch] $SelfTestContract,
    [Parameter(ParameterSetName = 'Run', Mandatory = $true)]
    [string] $ProtectedRecordPath,
    [Parameter(ParameterSetName = 'Run', Mandatory = $true)]
    [ValidateSet('fresh', 'resume', 'diagnostic', 'maintenance')]
    [string] $Operation,
    [Parameter(ParameterSetName = 'Run', Mandatory = $true)]
    [string] $ExpectedRecordSha256,
    [Parameter(ParameterSetName = 'Run', Mandatory = $true)]
    [string] $ExpectedHostPath,
    [Parameter(ParameterSetName = 'Run', Mandatory = $true)]
    [string] $ExpectedHostSha256,
    [Parameter(ParameterSetName = 'Run', Mandatory = $true)]
    [string] $ExpectedHostSignatureSha256,
    [Parameter(ParameterSetName = 'Run', Mandatory = $true)]
    [string] $ExpectedAnchorSha256,
    [Parameter(ParameterSetName = 'Run', Mandatory = $true)]
    [string] $JsonAssemblyPath,
    [Parameter(ParameterSetName = 'Run', Mandatory = $true)]
    [string] $ExpectedJsonAssemblySha256,
    [Parameter(ParameterSetName = 'Run')]
    [string] $MaintenanceRequestBase64Url
)

$ErrorActionPreference = 'Stop'
$script:ShaPattern = [System.Text.RegularExpressions.Regex]::new(
    '\A[0-9a-f]{64}\z',
    [System.Text.RegularExpressions.RegexOptions]::CultureInvariant)

function Assert-FullSha256 {
    param([Parameter(Mandatory = $true)][string] $Value, [string] $Label)
    if (-not $script:ShaPattern.IsMatch($Value)) {
        throw "$Label is not a full lowercase SHA-256"
    }
    return $Value
}

function ConvertTo-StrictDrivePath {
    param([Parameter(Mandatory = $true)][string] $Value, [string] $Label)
    if ([string]::IsNullOrWhiteSpace($Value) -or
            -not [System.Text.RegularExpressions.Regex]::IsMatch(
                $Value, '\A[A-Za-z]:[\\/](?![\\/])') -or
            $Value.StartsWith('\\') -or $Value.StartsWith('//')) {
        throw "$Label is not a strict local drive path"
    }
    $full = [System.IO.Path]::GetFullPath($Value.Replace('/', '\'))
    if ($full.StartsWith('\\?\') -or $full.StartsWith('\\.\')) {
        throw "$Label uses a device namespace"
    }
    return $full.TrimEnd('\')
}

function Assert-NoReparsePath {
    param([Parameter(Mandatory = $true)][string] $Path, [string] $Label)
    $full = ConvertTo-StrictDrivePath $Path $Label
    $root = [System.IO.Path]::GetPathRoot($full)
    $current = $root.TrimEnd('\')
    foreach ($component in $full.Substring($root.Length).Split([char]'\')) {
        if ($component.Length -eq 0) { continue }
        $current = [System.IO.Path]::Combine($current, $component)
        if ([System.IO.File]::Exists($current) -or
                [System.IO.Directory]::Exists($current)) {
            $attributes = [System.IO.File]::GetAttributes($current)
            if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label traverses a reparse point"
            }
        }
    }
    return $full
}

function Open-VerifiedFile {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $ExpectedSha256,
        [Parameter(Mandatory = $true)][string] $Label,
        [long] $MaximumBytes = 1048576
    )
    [void](Assert-FullSha256 $ExpectedSha256 "$Label digest")
    $full = Assert-NoReparsePath $Path $Label
    if (-not [System.IO.File]::Exists($full)) { throw "$Label is unavailable" }
    $stream = [System.IO.FileStream]::new(
        $full,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read,
        65536,
        [System.IO.FileOptions]::SequentialScan)
    try {
        if ($stream.Length -lt 1 -or $stream.Length -gt $MaximumBytes) {
            throw "$Label size is outside the closed limit"
        }
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try {
            $observed = ([System.BitConverter]::ToString(
                $sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
        }
        finally { $sha.Dispose() }
        if ($observed -cne $ExpectedSha256) { throw "$Label digest drift" }
        $stream.Position = 0
        $bytes = [byte[]]::new([int]$stream.Length)
        $offset = 0
        while ($offset -lt $bytes.Length) {
            $count = $stream.Read($bytes, $offset, $bytes.Length - $offset)
            if ($count -le 0) { throw "$Label read ended early" }
            $offset += $count
        }
        $after = Assert-NoReparsePath $full $Label
        if (-not $after.Equals($full, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "$Label identity path changed while open"
        }
        return ,$bytes
    }
    finally { $stream.Dispose() }
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string] $Path, [string] $Label)
    $full = Assert-NoReparsePath $Path $Label
    $stream = [System.IO.FileStream]::new(
        $full, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString(
            $sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function Get-StringSha256 {
    param([Parameter(Mandatory = $true)][string] $Value)
    $bytes = [System.Text.UTF8Encoding]::new($false, $true).GetBytes($Value)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString(
            $sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Get-PinnedHostSignatureRecord {
    param([Parameter(Mandatory = $true)][string] $Path)
    $signature = Microsoft.PowerShell.Security\Get-AuthenticodeSignature `
        -LiteralPath $Path -ErrorAction Stop
    if ($null -eq $signature -or $null -eq $signature.SignerCertificate -or
            [string]$signature.Status -cne 'Valid' -or
            -not [bool]$signature.IsOSBinary -or
            [string]$signature.SignatureType -notin @('Catalog', 'Authenticode')) {
        throw 'PowerShell host signature is not valid and OS-owned'
    }
    $subject = [string]$signature.SignerCertificate.Subject
    $thumbprint = ([string]$signature.SignerCertificate.Thumbprint).ToLowerInvariant()
    if (-not $subject.StartsWith(
            'CN=Microsoft Windows,', [System.StringComparison]::Ordinal) -or
            -not [System.Text.RegularExpressions.Regex]::IsMatch(
                $thumbprint, '\A[0-9a-f]{40}\z')) {
        throw 'PowerShell host signer identity is not pinned to Microsoft Windows'
    }
    return [ordered]@{
        is_os_binary = $true
        signature_type = [string]$signature.SignatureType
        signer_subject = $subject
        signer_thumbprint = $thumbprint
        status = 'Valid'
    }
}

function Close-AmbientEnvironment {
    param([Parameter(Mandatory = $true)][string] $WindowsRoot)
    $names = [string[]]@(
        [System.Environment]::GetEnvironmentVariables(
            [System.EnvironmentVariableTarget]::Process).Keys)
    foreach ($name in $names) {
        [System.Environment]::SetEnvironmentVariable(
            $name, $null, [System.EnvironmentVariableTarget]::Process)
    }
    [System.Environment]::SetEnvironmentVariable(
        'SystemRoot', $WindowsRoot, [System.EnvironmentVariableTarget]::Process)
    [System.Environment]::SetEnvironmentVariable(
        'WINDIR', $WindowsRoot, [System.EnvironmentVariableTarget]::Process)
}

function ConvertTo-CanonicalJsonString {
    param([AllowNull()] $Value)
    if ($null -eq $Value) { return 'null' }
    if ($Value -is [bool]) {
        if ($Value) { return 'true' }
        return 'false'
    }
    if ($Value -is [string]) {
        $builder = [System.Text.StringBuilder]::new()
        [void]$builder.Append('"')
        :characters foreach ($character in $Value.ToCharArray()) {
            $code = [int][char]$character
            switch ($code) {
                8 { [void]$builder.Append('\b'); continue characters }
                9 { [void]$builder.Append('\t'); continue characters }
                10 { [void]$builder.Append('\n'); continue characters }
                12 { [void]$builder.Append('\f'); continue characters }
                13 { [void]$builder.Append('\r'); continue characters }
                34 { [void]$builder.Append('\"'); continue characters }
                92 { [void]$builder.Append('\\'); continue characters }
            }
            if ($code -lt 32) {
                [void]$builder.Append('\u')
                [void]$builder.Append($code.ToString(
                    'x4', [System.Globalization.CultureInfo]::InvariantCulture))
            }
            else { [void]$builder.Append($character) }
        }
        [void]$builder.Append('"')
        return $builder.ToString()
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $keys = [string[]]@($Value.Keys)
        [System.Array]::Sort($keys, [System.StringComparer]::Ordinal)
        $parts = [System.Collections.Generic.List[string]]::new()
        foreach ($key in $keys) {
            [void]$parts.Add(
                (ConvertTo-CanonicalJsonString $key) + ':' +
                (ConvertTo-CanonicalJsonString $Value[$key]))
        }
        return '{' + [string]::Join(',', $parts) + '}'
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $parts = [System.Collections.Generic.List[string]]::new()
        foreach ($item in $Value) {
            [void]$parts.Add((ConvertTo-CanonicalJsonString $item))
        }
        return '[' + [string]::Join(',', $parts) + ']'
    }
    $integerTypes = @(
        [byte], [sbyte], [int16], [uint16], [int32], [uint32], [int64], [uint64])
    foreach ($type in $integerTypes) {
        if ($Value -is $type) {
            return [System.Convert]::ToString(
                $Value, [System.Globalization.CultureInfo]::InvariantCulture)
        }
    }
    throw 'JSON value type is outside the closed schema'
}

function Read-CanonicalJson {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $ExpectedSha256,
        [Parameter(Mandatory = $true)][string] $Label,
        [Parameter(Mandatory = $true)] $Serializer,
        [long] $MaximumBytes = 1048576
    )
    $bytes = Open-VerifiedFile $Path $ExpectedSha256 $Label $MaximumBytes
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 239 -and
            $bytes[1] -eq 187 -and $bytes[2] -eq 191) {
        throw "$Label has a forbidden BOM"
    }
    $utf8 = [System.Text.UTF8Encoding]::new($false, $true)
    $text = $utf8.GetString($bytes)
    try { $value = $Serializer.DeserializeObject($text) }
    catch { throw "$Label is not strict JSON" }
    if ($value -isnot [System.Collections.IDictionary] -or
            (ConvertTo-CanonicalJsonString $value) -cne $text) {
        throw "$Label is not canonical duplicate-free JSON"
    }
    return $value
}

function Assert-ExactKeys {
    param($Value, [string[]] $Keys, [string] $Label)
    if ($Value -isnot [System.Collections.IDictionary] -or
            $Value.Count -ne $Keys.Length) { throw "$Label fields are not closed" }
    foreach ($key in $Keys) {
        if (-not (Test-DictionaryKey $Value $key)) {
            throw "$Label field is absent: $key"
        }
    }
}

function Test-DictionaryKey {
    param($Value, [string] $Expected)
    if ($Value -isnot [System.Collections.IDictionary]) { return $false }
    foreach ($key in $Value.Keys) {
        if ([string]::Equals(
                [string]$key, $Expected,
                [System.StringComparison]::Ordinal)) { return $true }
    }
    return $false
}

function Assert-BeneathRecordRoot {
    param([string] $Path, [string] $Root, [string] $Label)
    $full = Assert-NoReparsePath $Path $Label
    $prefix = $Root.TrimEnd('\') + '\'
    if (-not $full.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label escapes the protected record root"
    }
    return $full
}

function ConvertFrom-StrictBase64Url {
    param(
        [Parameter(Mandatory = $true)][string] $Text,
        [Parameter(Mandatory = $true)][int] $MaximumEncodedLength,
        [Parameter(Mandatory = $true)][string] $Label
    )
    if ([string]::IsNullOrEmpty($Text) -or $Text.Length -gt $MaximumEncodedLength -or
            -not [System.Text.RegularExpressions.Regex]::IsMatch(
                $Text, '\A[A-Za-z0-9_-]+\z',
                [System.Text.RegularExpressions.RegexOptions]::CultureInvariant) -or
            ($Text.Length % 4) -eq 1) {
        throw "$Label is not bounded strict unpadded base64url"
    }
    $standard = $Text.Replace('-', '+').Replace('_', '/')
    $padding = (4 - ($standard.Length % 4)) % 4
    if ($padding -gt 0) { $standard += ('=' * $padding) }
    try { $bytes = [System.Convert]::FromBase64String($standard) }
    catch { throw "$Label base64url decode failed" }
    $canonical = [System.Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    if (-not [string]::Equals($Text, $canonical, [System.StringComparison]::Ordinal)) {
        throw "$Label base64url spelling is not canonical"
    }
    return ,$bytes
}

function Get-ExactSourceLeaf {
    param(
        [Parameter(Mandatory = $true)] $Receipt,
        [Parameter(Mandatory = $true)][string] $LogicalPath,
        [Parameter(Mandatory = $true)][string] $ExternalRoot
    )
    $matches = [System.Collections.Generic.List[object]]::new()
    foreach ($leaf in @($Receipt['source_leaves'])) {
        if ($leaf -is [System.Collections.IDictionary] -and
                (Test-DictionaryKey $leaf 'logical_path') -and
                [string]$leaf['logical_path'] -ceq $LogicalPath) {
            [void]$matches.Add($leaf)
        }
    }
    if ($matches.Count -ne 1) { throw "sealed source leaf is not unique: $LogicalPath" }
    $match = $matches[0]
    Assert-ExactKeys $match @('installed_path', 'logical_path', 'sha256', 'size') `
        "sealed source leaf $LogicalPath"
    $digest = Assert-FullSha256 ([string]$match['sha256']) "$LogicalPath digest"
    $path = Assert-BeneathRecordRoot ([string]$match['installed_path']) `
        $ExternalRoot $LogicalPath
    $bytes = Open-VerifiedFile $path $digest $LogicalPath 10485760
    if ($match['size'] -isnot [int] -and $match['size'] -isnot [long]) {
        throw "$LogicalPath size is malformed"
    }
    if ([long]$match['size'] -ne $bytes.LongLength) {
        throw "$LogicalPath size differs"
    }
    return $path
}

function ConvertTo-WindowsNativeArgument {
    param([Parameter(Mandatory = $true)][string] $Value)
    if ($Value.IndexOf([char]0) -ge 0 -or $Value.Contains("`r") -or
            $Value.Contains("`n") -or $Value.Length -gt 8192) {
        throw 'child argument is malformed'
    }
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $builder = [System.Text.StringBuilder]::new()
    [void]$builder.Append('"')
    $slashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') { $slashes += 1; continue }
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

if ($SelfTestContract) {
    [System.Console]::Out.Write(
        '{"activation_authority":false,"ambient_command_resolution":false,' +
        '"inherited_environment":false,"inherited_stdio":false,"pre_python":true,' +
        '"schema":"galaxy.singularity-anchor-self-test/v1",' +
        '"supported_operations":["diagnostic","fresh","maintenance","resume"]}')
    exit 0
}

try {
    [void](Assert-FullSha256 $ExpectedRecordSha256 'record digest')
    [void](Assert-FullSha256 $ExpectedHostSha256 'host digest')
    [void](Assert-FullSha256 $ExpectedHostSignatureSha256 'host signature digest')
    [void](Assert-FullSha256 $ExpectedAnchorSha256 'anchor digest')
    [void](Assert-FullSha256 $ExpectedJsonAssemblySha256 'JSON assembly digest')
    $actualHost = Assert-NoReparsePath (
        [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName) 'host'
    $expectedHost = Assert-NoReparsePath $ExpectedHostPath 'expected host'
    if (-not $actualHost.Equals(
            $expectedHost, [System.StringComparison]::OrdinalIgnoreCase) -or
            (Get-FileSha256 $actualHost 'host') -cne $ExpectedHostSha256) {
        throw 'PowerShell host identity or digest drift'
    }
    $hostSuffix = '\System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not $actualHost.EndsWith(
            $hostSuffix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'PowerShell host path is outside the pinned Windows location'
    }
    $windowsRoot = $actualHost.Substring(0, $actualHost.Length - $hostSuffix.Length)
    Close-AmbientEnvironment $windowsRoot
    $hostSignature = Get-PinnedHostSignatureRecord $actualHost
    $hostSignatureJson = ConvertTo-CanonicalJsonString $hostSignature
    if ((Get-StringSha256 $hostSignatureJson) -cne $ExpectedHostSignatureSha256) {
        throw 'PowerShell host signature record drift'
    }
    $anchorPath = Assert-NoReparsePath $PSCommandPath 'anchor source'
    if ((Get-FileSha256 $anchorPath 'anchor source') -cne $ExpectedAnchorSha256) {
        throw 'anchor source digest drift'
    }
    $assemblyPath = Assert-NoReparsePath $JsonAssemblyPath 'JSON parser assembly'
    if ((Get-FileSha256 $assemblyPath 'JSON parser assembly') -cne
            $ExpectedJsonAssemblySha256) {
        throw 'JSON parser assembly digest drift'
    }
    [void][System.Reflection.Assembly]::LoadFile($assemblyPath)
    $serializer = [System.Web.Script.Serialization.JavaScriptSerializer]::new()
    $serializer.MaxJsonLength = 1048576

    $record = Read-CanonicalJson $ProtectedRecordPath $ExpectedRecordSha256 `
        'anchor record' $serializer 65536
    Assert-ExactKeys $record @(
        'activation_state', 'capsule_path', 'capsule_sha256', 'generation',
        'generation_path', 'runtime_manifest_path', 'runtime_manifest_sha256',
        'schema') 'anchor record'
    if ($record['schema'] -ne 1 -or $record['generation'] -lt 1 -or
            $record['activation_state'] -notin @('inactive', 'active')) {
        throw 'anchor record schema or generation is invalid'
    }
    $isMaintenance = $Operation -ceq 'maintenance'
    if ($isMaintenance) {
        if ($record['activation_state'] -cne 'inactive' -or
                [string]::IsNullOrEmpty($MaintenanceRequestBase64Url)) {
            throw 'maintenance requires an exact inactive generation and request'
        }
    }
    elseif ($record['activation_state'] -cne 'active') {
        # Inactive normal launches stop at the anchor record.  They must not
        # probe a later runtime lock or capsule and turn poisoned authority
        # material into a different observable outcome.
        throw 'TransactionalKernelInactive: installed controller generation is inactive'
    }
    elseif (-not [string]::IsNullOrEmpty($MaintenanceRequestBase64Url)) {
        throw 'normal controller launch cannot carry a maintenance request'
    }
    $recordPath = Assert-NoReparsePath $ProtectedRecordPath 'anchor record'
    $recordRoot = [System.IO.Path]::GetDirectoryName($recordPath)
    $capsule = Assert-BeneathRecordRoot ([string]$record['capsule_path']) `
        $recordRoot 'capsule'
    $manifestPath = Assert-BeneathRecordRoot `
        ([string]$record['runtime_manifest_path']) $recordRoot 'runtime manifest'
    $generationPath = Assert-BeneathRecordRoot `
        ([string]$record['generation_path']) $recordRoot 'generation'
    $capsuleDigest = Assert-FullSha256 ([string]$record['capsule_sha256']) `
        'capsule digest'
    $manifestDigest = Assert-FullSha256 `
        ([string]$record['runtime_manifest_sha256']) 'runtime manifest digest'
    [void](Open-VerifiedFile $capsule $capsuleDigest 'capsule' 10485760)
    $generationBytes = Open-VerifiedFile $generationPath `
        (Get-FileSha256 $generationPath 'generation') 'generation' 32
    $generationText = [System.Text.Encoding]::ASCII.GetString($generationBytes)
    if ($generationText -cne [string]$record['generation']) {
        throw 'generation file is not exact and monotonic'
    }
    $manifest = Read-CanonicalJson $manifestPath $manifestDigest `
        'runtime manifest' $serializer 65536
    Assert-ExactKeys $manifest @(
        'activation_state', 'closed', 'generation', 'runtime_digest',
        'runtime_lock_path', 'runtime_lock_sha256', 'schema') 'runtime manifest'
    if ($manifest['schema'] -ne 1 -or $manifest['closed'] -ne $true -or
            $manifest['generation'] -ne $record['generation'] -or
            $manifest['activation_state'] -cne $record['activation_state']) {
        throw 'runtime manifest does not match the protected record'
    }
    [void](Assert-FullSha256 ([string]$manifest['runtime_digest']) 'runtime digest')
    $lockDigest = Assert-FullSha256 `
        ([string]$manifest['runtime_lock_sha256']) 'runtime lock digest'

    $lock = Read-CanonicalJson ([string]$manifest['runtime_lock_path']) `
        $lockDigest 'runtime lock' $serializer 1048576
    Assert-ExactKeys $lock @(
        'external_root', 'file_digests', 'files', 'generation',
        'image_archive_paths', 'image_digests', 'max_probe_concurrency',
        'runtime_digest', 'schema', 'security_profiles', 'status',
        'tofu_receipt_path') 'runtime lock'
    if ($lock['schema'] -cne 'galaxy.activation.sealed-runtime/v1' -or
            $lock['status'] -cne 'installed_inactive' -or
            $lock['generation'] -ne $record['generation'] -or
            $lock['runtime_digest'] -cne $manifest['runtime_digest']) {
        throw 'runtime lock does not match the protected generation'
    }
    $files = $lock['files']
    $digests = $lock['file_digests']
    if ($files -isnot [System.Collections.IDictionary] -or
            $digests -isnot [System.Collections.IDictionary] -or
            -not (Test-DictionaryKey $files 'interpreter') -or
            -not (Test-DictionaryKey $digests 'interpreter')) {
        throw 'runtime lock has no exact interpreter binding'
    }
    $interpreterDigest = Assert-FullSha256 `
        ([string]$digests['interpreter']) 'interpreter digest'
    $interpreter = Assert-NoReparsePath ([string]$files['interpreter']) 'interpreter'
    [void](Open-VerifiedFile $interpreter $interpreterDigest 'interpreter' 104857600)

    $empty = [System.IO.Path]::Combine($recordRoot, 'empty-cwd')
    if ([System.IO.File]::Exists($empty)) { throw 'empty cwd path is a file' }
    if (-not [System.IO.Directory]::Exists($empty)) {
        [void][System.IO.Directory]::CreateDirectory($empty)
    }
    if ([System.IO.Directory]::GetFileSystemEntries($empty).Length -ne 0) {
        throw 'sealed working directory is not empty'
    }
    $childValues = if ($isMaintenance) {
        $requestBytes = ConvertFrom-StrictBase64Url `
            $MaintenanceRequestBase64Url 10923 'maintenance request'
        if ($requestBytes.Length -gt 8192) {
            throw 'maintenance request decoded byte cap exceeded'
        }
        $utf8 = [System.Text.UTF8Encoding]::new($false, $true)
        try { $requestText = $utf8.GetString($requestBytes) }
        catch { throw 'maintenance request is not strict UTF-8' }
        try { $requestValue = $serializer.DeserializeObject($requestText) }
        catch { throw 'maintenance request is not JSON' }
        Assert-ExactKeys $requestValue @(
            'arguments', 'operation', 'payload_base64url', 'request_id') `
            'maintenance request'
        if ((ConvertTo-CanonicalJsonString $requestValue) -cne $requestText) {
            throw 'maintenance request is not byte-exact canonical JSON'
        }
        $externalRoot = Assert-NoReparsePath ([string]$lock['external_root']) `
            'external root'
        $runtimeLockPath = Assert-BeneathRecordRoot `
            ([string]$manifest['runtime_lock_path']) $externalRoot 'runtime lock'
        $receiptPath = Assert-BeneathRecordRoot ([string]$lock['tofu_receipt_path']) `
            $externalRoot 'TOFU receipt'
        $receipt = Read-CanonicalJson $receiptPath `
            (Get-FileSha256 $receiptPath 'TOFU receipt') 'TOFU receipt' $serializer 33554432
        if ([string]$receipt['schema'] -cne 'galaxy.trust-on-first-install/v1' -or
                [string]$receipt['status'] -cne 'installed_inactive' -or
                [string]$receipt['activation_state'] -cne 'inactive') {
            throw 'TOFU receipt does not bind an inactive installation'
        }
        $adminSource = Get-ExactSourceLeaf $receipt 'bootstrap/anchor.py' $externalRoot
        @(
            '-I', '-S', '-B', $adminSource,
            '--admin-request-base64url', $MaintenanceRequestBase64Url,
            '--runtime-lock-path', $runtimeLockPath,
            '--runtime-lock-sha256', $lockDigest
        )
    }
    else { @('-I', '-S', '-B', $capsule, $Operation) }
    $childArguments = [System.Collections.Generic.List[string]]::new()
    foreach ($value in $childValues) {
        [void]$childArguments.Add((ConvertTo-WindowsNativeArgument $value))
    }
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $interpreter
    $start.Arguments = [string]::Join(' ', $childArguments)
    $start.WorkingDirectory = $empty
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.EnvironmentVariables.Clear()
    $start.EnvironmentVariables['SystemRoot'] = $windowsRoot
    $start.EnvironmentVariables['WINDIR'] = $windowsRoot
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $start
    if (-not $process.Start()) { throw 'sealed controller child did not start' }
    $process.StandardInput.Close()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    [System.Threading.Tasks.Task]::WaitAll(@($stdoutTask, $stderrTask))
    $exitCode = $process.ExitCode
    $childStdout = $stdoutTask.Result
    $childStderr = $stderrTask.Result
    $process.Dispose()
    if ($isMaintenance) {
        if ($childStdout.Length -gt 1048576 -or $childStderr.Length -gt 1048576) {
            throw 'sealed maintenance child output exceeds its bound'
        }
        if ($childStdout.Length -gt 0) { [System.Console]::Out.Write($childStdout) }
        if ($childStderr.Length -gt 0) { [System.Console]::Error.Write($childStderr) }
    }
    exit $exitCode
}
catch {
    [System.Console]::Error.WriteLine('SingularityAnchorRefused: ' + $_.Exception.Message)
    if ($_.Exception.Message.StartsWith('TransactionalKernelInactive:')) { exit 78 }
    exit 79
}
