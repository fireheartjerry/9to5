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

    [Parameter(ParameterSetName = 'Request')]
    [string] $Operation,

    [Parameter(ParameterSetName = 'Request')]
    [Alias('payload-base64url')]
    [string] $PayloadBase64Url,

    [Parameter(ParameterSetName = 'Request')]
    [Alias('require-server-validated-client-digest')]
    [switch] $RequireServerValidatedClientDigest
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
    $requestBytes = ConvertFrom-StrictBase64Url $Encoded 8192 'request envelope'
    $request = ConvertFrom-StrictUtf8Json $requestBytes 'request envelope'
    $names = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    foreach ($property in $request.PSObject.Properties) { [void] $names.Add($property.Name) }
    if ($names.Count -ne 3 -or -not $names.Contains('operation') -or
            -not $names.Contains('payload_base64url') -or -not $names.Contains('request_id')) {
        throw 'request envelope schema mismatch'
    }
    if ($request.operation -ne 'append-path-manifest' -or
            $request.payload_base64url -isnot [string] -or $request.request_id -isnot [string]) {
        throw 'request envelope field mismatch'
    }
    $payloadBytes = ConvertFrom-StrictBase64Url $request.payload_base64url 8192 'path manifest'
    if ($payloadBytes.Length -gt 4096) { throw 'path manifest decoded byte cap exceeded' }
    [void] (ConvertFrom-StrictUtf8Json $payloadBytes 'path manifest')
    $output = '{"canonical_request_base64url":' + (ConvertTo-JsonString $Encoded) +
        ',"payload_base64url":' + (ConvertTo-JsonString $request.payload_base64url) + '}'
    [System.Console]::Out.WriteLine($output)
}

try {
    if ($PSCmdlet.ParameterSetName -eq 'SelfTest') {
        Invoke-RequestEnvelopeSelfTest $SelfTestRequestEnvelope
        exit 0
    }
    if (-not $RequestOnly -or [string]::IsNullOrEmpty($Operation) -or
            [string]::IsNullOrEmpty($PayloadBase64Url) -or
            -not $RequireServerValidatedClientDigest) {
        throw 'request-only closed protocol arguments are required'
    }
    [System.Console]::Out.WriteLine('{"accepted":false,"error":"TransactionalKernelInactive"}')
    exit 73
}
catch {
    [System.Console]::Error.WriteLine('Singularity request refused: ' + $_.Exception.Message)
    exit 2
}
