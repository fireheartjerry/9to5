<#
Request-only client for the installed GALAXY Singularity anchor.

The self-test path is intentionally complete in the source tree so TOFU can
verify the exact PowerShell 5.1 canonical-envelope implementation before an
installed pipe endpoint exists.  Normal requests fail closed while inactive.
#>
[CmdletBinding(DefaultParameterSetName = 'Request')]
param(
    [Parameter(ParameterSetName = 'SelfTest', Mandatory = $true)]
    [string] $SelfTestRequestEnvelope,

    [Parameter(ParameterSetName = 'Request')]
    [Alias('request-only')]
    [switch] $RequestOnly,

    [Parameter(ParameterSetName = 'Request', Position = 0)]
    [string] $Operation,

    [Parameter(ParameterSetName = 'Request')]
    [Alias('payload-base64url')]
    [string] $PayloadBase64Url,

    [Parameter(ParameterSetName = 'Request')]
    [Alias('arguments-base64url')]
    [string] $ArgumentsBase64Url,

    [Parameter(ParameterSetName = 'Request')]
    [Alias('envelope-request-id')]
    [string] $EnvelopeRequestId,

    [Parameter(ParameterSetName = 'Request')]
    [Alias('require-server-validated-client-digest')]
    [switch] $RequireServerValidatedClientDigest,

    [Parameter(ParameterSetName = 'Request')]
    [Alias('emit-canonical-response')]
    [switch] $EmitCanonicalResponse,

    [Parameter(ParameterSetName = 'Request', ValueFromRemainingArguments = $true)]
    [string[]] $InvocationArguments
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function ConvertFrom-StrictBase64Url {
    param(
        [Parameter(Mandatory = $true)][string] $Text,
        [Parameter(Mandatory = $true)][int] $MaximumEncodedLength,
        [Parameter(Mandatory = $true)][string] $Label
    )
    if ([string]::IsNullOrEmpty($Text) -or $Text.Length -gt $MaximumEncodedLength) {
        throw "$Label encoded length is outside its bound"
    }
    if (-not [System.Text.RegularExpressions.Regex]::IsMatch(
            $Text, '\A[A-Za-z0-9_-]+\z',
            [System.Text.RegularExpressions.RegexOptions]::CultureInvariant)) {
        throw "$Label is not strict unpadded base64url"
    }
    if (($Text.Length % 4) -eq 1) {
        throw "$Label has an impossible base64url length"
    }
    $standard = $Text.Replace('-', '+').Replace('_', '/')
    $padding = (4 - ($standard.Length % 4)) % 4
    if ($padding -gt 0) {
        $standard = $standard + ('=' * $padding)
    }
    try {
        $bytes = [System.Convert]::FromBase64String($standard)
    }
    catch {
        throw "$Label base64url decode failed"
    }
    $reencoded = [System.Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    if (-not [string]::Equals($Text, $reencoded, [System.StringComparison]::Ordinal)) {
        throw "$Label base64url spelling is not canonical"
    }
    return ,$bytes
}

function ConvertTo-JsonString {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string] $Value)
    $builder = New-Object System.Text.StringBuilder
    [void] $builder.Append('"')
    foreach ($character in $Value.ToCharArray()) {
        $code = [int][char]$character
        $escaped = $null
        switch ($code) {
            8  { $escaped = '\b' }
            9  { $escaped = '\t' }
            10 { $escaped = '\n' }
            12 { $escaped = '\f' }
            13 { $escaped = '\r' }
            34 { $escaped = '\"' }
            92 { $escaped = '\\' }
        }
        if ($null -ne $escaped) {
            [void] $builder.Append($escaped)
        }
        elseif ($code -lt 32) {
            [void] $builder.Append(('\u{0:x4}' -f $code))
        }
        else {
            [void] $builder.Append($character)
        }
    }
    [void] $builder.Append('"')
    return $builder.ToString()
}

function ConvertTo-CanonicalJson {
    param([Parameter(Mandatory = $false)] $Value)
    if ($null -eq $Value) { return 'null' }
    if ($Value -is [string]) { return ConvertTo-JsonString ([string]$Value) }
    if ($Value -is [bool]) { if ($Value) { return 'true' } else { return 'false' } }
    if ($Value -is [System.Collections.IDictionary]) {
        $names = New-Object 'System.Collections.Generic.List[string]'
        foreach ($key in $Value.Keys) { $names.Add([string]$key) }
        $names.Sort([System.StringComparer]::Ordinal)
        $members = New-Object 'System.Collections.Generic.List[string]'
        foreach ($name in $names) {
            $members.Add((ConvertTo-JsonString $name) + ':' + (ConvertTo-CanonicalJson $Value[$name]))
        }
        return '{' + [string]::Join(',', $members.ToArray()) + '}'
    }
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        $names = New-Object 'System.Collections.Generic.List[string]'
        foreach ($property in $Value.PSObject.Properties) { $names.Add($property.Name) }
        $names.Sort([System.StringComparer]::Ordinal)
        $members = New-Object 'System.Collections.Generic.List[string]'
        foreach ($name in $names) {
            $members.Add((ConvertTo-JsonString $name) + ':' +
                (ConvertTo-CanonicalJson $Value.PSObject.Properties[$name].Value))
        }
        return '{' + [string]::Join(',', $members.ToArray()) + '}'
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $items = New-Object 'System.Collections.Generic.List[string]'
        foreach ($item in $Value) { $items.Add((ConvertTo-CanonicalJson $item)) }
        return '[' + [string]::Join(',', $items.ToArray()) + ']'
    }
    if ($Value -is [byte] -or $Value -is [int16] -or $Value -is [int32] -or
            $Value -is [int64] -or $Value -is [decimal] -or $Value -is [double]) {
        return [System.Convert]::ToString($Value, [System.Globalization.CultureInfo]::InvariantCulture)
    }
    throw 'request contains an unsupported JSON value'
}

function ConvertFrom-StrictUtf8Json {
    param(
        [Parameter(Mandatory = $true)][byte[]] $Bytes,
        [Parameter(Mandatory = $true)][string] $Label
    )
    $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
    try { $text = $utf8.GetString($Bytes) }
    catch { throw "$Label is not strict UTF-8" }
    if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) {
        throw "$Label UTF-8 BOM is forbidden"
    }
    try { $value = $text | ConvertFrom-Json }
    catch { throw "$Label is not JSON" }
    if ($null -eq $value -or $value -isnot [System.Management.Automation.PSCustomObject]) {
        throw "$Label must be a JSON object"
    }
    $canonical = ConvertTo-CanonicalJson $value
    if (-not [string]::Equals($text, $canonical, [System.StringComparison]::Ordinal)) {
        throw "$Label is not byte-exact canonical JSON"
    }
    return $value
}

function Invoke-RequestEnvelopeSelfTest {
    param([Parameter(Mandatory = $true)][string] $Encoded)
    # The self-test transports the raw pipe frame through argv once more.  Its
    # base64url wrapper may be 10,923 characters while the decoded request
    # itself remains capped at the protocol's exact 8 KiB.
    $requestBytes = ConvertFrom-StrictBase64Url $Encoded 10923 'request envelope'
    if ($requestBytes.Length -gt 8192) { throw 'request envelope decoded byte cap exceeded' }
    $request = ConvertFrom-StrictUtf8Json $requestBytes 'request envelope'
    $names = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    foreach ($property in $request.PSObject.Properties) { [void] $names.Add($property.Name) }
    if ($names.Count -ne 4 -or -not $names.Contains('arguments') -or
            -not $names.Contains('operation') -or
            -not $names.Contains('payload_base64url') -or -not $names.Contains('request_id')) {
        throw 'request envelope schema mismatch'
    }
    if ($request.operation -ne 'append-path-manifest' -or
            $request.arguments -isnot [System.Management.Automation.PSCustomObject] -or
            $request.payload_base64url -isnot [string] -or
            $request.request_id -isnot [string]) {
        throw 'request envelope field mismatch'
    }
    $payloadBytes = ConvertFrom-StrictBase64Url $request.payload_base64url 8192 'path manifest'
    if ($payloadBytes.Length -gt 4096) { throw 'path manifest decoded byte cap exceeded' }
    [void] (ConvertFrom-StrictUtf8Json $payloadBytes 'path manifest')
    $output = '{"canonical_request_base64url":' + (ConvertTo-JsonString $Encoded) +
        ',"payload_base64url":' + (ConvertTo-JsonString $request.payload_base64url) + '}'
    [System.Console]::Out.WriteLine($output)
}

function ConvertFrom-InvocationArguments {
    param([string[]] $Tokens)
    $result = [ordered]@{}
    $index = 0
    while ($index -lt $Tokens.Count) {
        $token = [string]$Tokens[$index]
        if (-not [System.Text.RegularExpressions.Regex]::IsMatch(
                $token, '\A--[a-z][a-z0-9-]{0,63}\z',
                [System.Text.RegularExpressions.RegexOptions]::CultureInvariant)) {
            throw "operation argument token is malformed: $token"
        }
        $key = $token.Substring(2).Replace('-', '_')
        if ($result.Contains($key)) { throw "operation argument is duplicated: $token" }
        $value = $true
        if ($index + 1 -lt $Tokens.Count -and
                -not ([string]$Tokens[$index + 1]).StartsWith('--')) {
            $index += 1
            $raw = [string]$Tokens[$index]
            if ($raw.Length -gt 32767 -or $raw.IndexOf([char]0) -ge 0 -or
                    $raw.Contains("`r") -or $raw.Contains("`n")) {
                throw "operation argument value is malformed: $token"
            }
            if ([System.Text.RegularExpressions.Regex]::IsMatch(
                    $raw, '\A(?:0|[1-9][0-9]{0,17})\z',
                    [System.Text.RegularExpressions.RegexOptions]::CultureInvariant)) {
                $value = [System.Int64]::Parse(
                    $raw, [System.Globalization.CultureInfo]::InvariantCulture)
            }
            else { $value = $raw }
        }
        $result[$key] = $value
        $index += 1
    }
    return $result
}

function ConvertTo-Base64UrlUtf8 {
    param([Parameter(Mandatory = $true)][string] $Text)
    $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
    return [System.Convert]::ToBase64String($utf8.GetBytes($Text)).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Get-Utf8Sha256 {
    param([Parameter(Mandatory = $true)][string] $Text)
    $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString(
            $sha.ComputeHash($utf8.GetBytes($Text)))).Replace('-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Read-ExactPipeBytes {
    param(
        [Parameter(Mandatory = $true)][System.IO.Stream] $Stream,
        [Parameter(Mandatory = $true)][int] $Count,
        [Parameter(Mandatory = $true)][string] $Label
    )
    if ($Count -lt 0 -or $Count -gt 1048576) { throw "$Label length is outside its bound" }
    $bytes = [byte[]]::new($Count)
    $offset = 0
    while ($offset -lt $Count) {
        $read = $Stream.Read($bytes, $offset, $Count - $offset)
        if ($read -le 0) { throw "$Label pipe frame ended early" }
        $offset += $read
    }
    return ,$bytes
}

function ConvertTo-BigEndianLength {
    param([Parameter(Mandatory = $true)][int] $Value)
    if ($Value -lt 1 -or $Value -gt 1048576) { throw 'pipe frame length is outside its bound' }
    return ,[byte[]]@(
        [byte](($Value -shr 24) -band 255),
        [byte](($Value -shr 16) -band 255),
        [byte](($Value -shr 8) -band 255),
        [byte]($Value -band 255)
    )
}

function ConvertFrom-BigEndianLength {
    param([Parameter(Mandatory = $true)][byte[]] $Bytes)
    if ($Bytes.Length -ne 4) { throw 'pipe frame header length differs' }
    $value = ([int]$Bytes[0] -shl 24) -bor ([int]$Bytes[1] -shl 16) -bor `
        ([int]$Bytes[2] -shl 8) -bor [int]$Bytes[3]
    if ($value -lt 1 -or $value -gt 1048576) { throw 'pipe response length is outside its bound' }
    return $value
}

function Invoke-ProtectedPipeRequest {
    param([Parameter(Mandatory = $true)][byte[]] $RequestBytes)
    if ($RequestBytes.Length -lt 1 -or $RequestBytes.Length -gt 8192) {
        throw 'request envelope byte length is outside 1..8192'
    }
    function New-ExactPipeClient {
        return [System.IO.Pipes.NamedPipeClientStream]::new(
            '.', '9to5-singularity-v1', [System.IO.Pipes.PipeDirection]::InOut,
            [System.IO.Pipes.PipeOptions]::None,
            [System.Security.Principal.TokenImpersonationLevel]::Identification)
    }
    function Start-ExactSingularityService {
        $controller = [System.ServiceProcess.ServiceController]::new(
            '9to5Singularity', '.')
        try {
            $controller.Refresh()
            if ($controller.Status -eq [System.ServiceProcess.ServiceControllerStatus]::Stopped) {
                $controller.Start()
            }
            if ($controller.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Running) {
                $controller.WaitForStatus(
                    [System.ServiceProcess.ServiceControllerStatus]::Running,
                    [System.TimeSpan]::FromSeconds(5))
            }
        }
        finally { $controller.Dispose() }
    }
    $pipe = New-ExactPipeClient
    try {
        try { $pipe.Connect(250) }
        catch {
            $pipe.Dispose()
            Start-ExactSingularityService
            $pipe = New-ExactPipeClient
            $pipe.Connect(5000)
        }
        $header = ConvertTo-BigEndianLength $RequestBytes.Length
        $pipe.Write($header, 0, $header.Length)
        $pipe.Write($RequestBytes, 0, $RequestBytes.Length)
        $pipe.Flush()
        $responseHeader = Read-ExactPipeBytes $pipe 4 'response header'
        $responseLength = ConvertFrom-BigEndianLength $responseHeader
        return ,(Read-ExactPipeBytes $pipe $responseLength 'response')
    }
    finally { $pipe.Dispose() }
}

try {
    if ($PSCmdlet.ParameterSetName -eq 'SelfTest') {
        Invoke-RequestEnvelopeSelfTest $SelfTestRequestEnvelope
        exit 0
    }
    $closedOperations = New-Object 'System.Collections.Generic.HashSet[string]' (
        [System.StringComparer]::Ordinal)
    foreach ($name in @(
            'abort-cutover', 'abort-path-manifest', 'abort-source-update',
            'acknowledge-terminal-disposition', 'acquire-begin-intent',
            'acquire-transition-purpose', 'append-path-manifest',
            'attest-committed-source', 'attest-target', 'begin-cutover',
            'begin-path-manifest', 'begin-source-update',
            'classify-purpose-successor', 'commit-source-proposal',
            'current-tofu-receipt', 'finish-cutover', 'finish-source-update',
            'handoff-to-anchor', 'install-inactive',
            'normalize-bootstrap-git-config', 'normalize-bootstrap-ref',
            'normalize-developer-source', 'observe-top-level-transition',
            'prepare-source-commit', 'reconcile-cutover-failure',
            'reconcile-source-commit', 'reconcile-source-update',
            'resolve-begin-intent', 'resolve-begin-intent-owner-fence',
            'resolve-current-top-level-transition', 'resolve-cutover-begin',
            'resolve-cutover-disposition', 'resolve-source-commit-disposition',
            'resolve-source-update-begin', 'resolve-source-update-disposition',
            'resolve-transition-purpose', 'resolve-transition-purpose-outcome',
            'review-source-proposal', 'seal-path-manifest',
            'settle-top-level-transition', 'verify-cutover', 'verify-drained',
            'verify-proposal-trust-closure', 'verify-self',
            'verify-source-proposal', 'verify-tofu-receipt')) {
        [void]$closedOperations.Add($name)
    }
    $providedInvocationArguments = @(
        $InvocationArguments | Where-Object { $null -ne $_ }
    )
    if ([string]::IsNullOrEmpty($Operation)) {
        $operationCandidates = @(
            $providedInvocationArguments | Where-Object {
                $closedOperations.Contains([string]$_)
            }
        )
        if ($operationCandidates.Count -ne 1) {
            throw 'request contains no unique closed operation token'
        }
        $Operation = [string]$operationCandidates[0]
        $remaining = New-Object 'System.Collections.Generic.List[string]'
        $removed = $false
        foreach ($token in $providedInvocationArguments) {
            if (-not $removed -and [string]$token -ceq $Operation) {
                $removed = $true
                continue
            }
            $remaining.Add([string]$token)
        }
        $providedInvocationArguments = $remaining.ToArray()
    }
    elseif (-not $closedOperations.Contains($Operation) -or
            @($providedInvocationArguments | Where-Object {
                $closedOperations.Contains([string]$_)
            }).Count -gt 0) {
        throw 'request operation is duplicated or outside the closed enum'
    }
    if (-not $RequestOnly -or [string]::IsNullOrEmpty($Operation) -or
            -not $RequireServerValidatedClientDigest) {
        throw 'request-only closed protocol arguments are required'
    }
    if (-not [System.Text.RegularExpressions.Regex]::IsMatch(
            $Operation, '\A[a-z][a-z0-9-]{0,63}\z',
            [System.Text.RegularExpressions.RegexOptions]::CultureInvariant)) {
        throw 'operation is outside the bounded token grammar'
    }
    $identityForValidation = if ([string]::IsNullOrEmpty($EnvelopeRequestId)) {
        'request_x'
    } else { $EnvelopeRequestId }
    if (-not [System.Text.RegularExpressions.Regex]::IsMatch(
            $identityForValidation,
            '\A[A-Za-z][A-Za-z0-9_.:-]{0,511}\z',
            [System.Text.RegularExpressions.RegexOptions]::CultureInvariant)) {
        throw 'request identity is outside the bounded token grammar'
    }
    if (-not [string]::IsNullOrEmpty($ArgumentsBase64Url)) {
        if ($providedInvocationArguments.Count -gt 0) {
            throw 'explicit argument envelope cannot be combined with plan-style flags'
        }
        $argumentBytes = ConvertFrom-StrictBase64Url $ArgumentsBase64Url 5462 'arguments'
        if ($argumentBytes.Length -gt 4096) { throw 'arguments decoded byte cap exceeded' }
        $arguments = ConvertFrom-StrictUtf8Json $argumentBytes 'arguments'
    }
    else { $arguments = ConvertFrom-InvocationArguments $providedInvocationArguments }
    if ([string]::IsNullOrEmpty($PayloadBase64Url) -and
            $arguments -is [System.Collections.IDictionary] -and
            $arguments.Contains('canonical_records_json_base64url')) {
        $PayloadBase64Url = [string]$arguments['canonical_records_json_base64url']
        [void]$arguments.Remove('canonical_records_json_base64url')
    }
    if ([string]::IsNullOrEmpty($PayloadBase64Url)) {
        $PayloadBase64Url = ConvertTo-Base64UrlUtf8 '{}'
    }
    $payloadBytes = ConvertFrom-StrictBase64Url $PayloadBase64Url 5462 'payload'
    if ($payloadBytes.Length -gt 4096) { throw 'payload decoded byte cap exceeded' }
    [void](ConvertFrom-StrictUtf8Json $payloadBytes 'payload')
    if ([string]::IsNullOrEmpty($EnvelopeRequestId)) {
        $identity = [ordered]@{
            arguments = $arguments
            operation = $Operation
            payload_base64url = $PayloadBase64Url
        }
        $EnvelopeRequestId = 'request_' + (Get-Utf8Sha256 (ConvertTo-CanonicalJson $identity))
    }
    $request = [ordered]@{
        arguments = $arguments
        operation = $Operation
        payload_base64url = $PayloadBase64Url
        request_id = $EnvelopeRequestId
    }
    $requestText = ConvertTo-CanonicalJson $request
    $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $requestBytes = $utf8.GetBytes($requestText)
    $responseBytes = Invoke-ProtectedPipeRequest $requestBytes
    $response = ConvertFrom-StrictUtf8Json $responseBytes 'response'
    $responseText = ConvertTo-CanonicalJson $response
    $responseNames = New-Object 'System.Collections.Generic.HashSet[string]' (
        [System.StringComparer]::Ordinal)
    foreach ($property in $response.PSObject.Properties) {
        [void]$responseNames.Add($property.Name)
    }
    foreach ($requiredName in @(
            'accepted', 'authority_ceiling', 'operation', 'production_active',
            'request_id', 'result', 'schema')) {
        if (-not $responseNames.Contains($requiredName)) {
            throw 'response schema is not closed'
        }
    }
    if ($responseNames.Count -ne 7 -or
            $response.schema -cne 'galaxy.singularity-admin-response/v1' -or
            $response.authority_ceiling -cne 'maintenance_only' -or
            $response.production_active -ne $false -or
            $response.operation -cne $Operation -or
            $response.request_id -cne $EnvelopeRequestId -or
            $response.result -isnot [System.Management.Automation.PSCustomObject]) {
        throw 'response authority or request binding differs'
    }
    if ($response.accepted -ne $true) {
        [System.Console]::Error.WriteLine($responseText)
        exit 73
    }
    if ($EmitCanonicalResponse) {
        [System.Console]::Out.WriteLine($responseText)
    }
    else {
        $outputProperty = $response.result.PSObject.Properties['output']
        if ($null -ne $outputProperty) {
            $output = $outputProperty.Value
            if ($output -isnot [string] -or $output.Length -gt 32767 -or
                    $output.IndexOf([char]0) -ge 0 -or $output.Contains("`r") -or
                    $output.Contains("`n")) {
                throw 'response output is not one bounded scalar line'
            }
            if ($output.Length -gt 0) { [System.Console]::Out.WriteLine($output) }
        }
    }
    exit 0
}
catch {
    [System.Console]::Error.WriteLine('Singularity request refused: ' + $_.Exception.Message)
    exit 2
}
