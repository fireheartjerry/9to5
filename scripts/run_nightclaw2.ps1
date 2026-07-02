<#
.SYNOPSIS
  Launch a SECOND, fully-isolated Nightclaw gateway using a separate Discord app token.

.DESCRIPTION
  Reads KEY=VALUE pairs from .env.nightclaw2 (gitignored), exports the Discord
  credentials as process env vars, redirects the file log to logs2/ so it never
  collides with the live instance, and starts `python -m nightclaw` from the
  worktree root. Because it runs from the worktree, config.PROJECT_ROOT resolves
  to the worktree — its state/control/tasks dirs are its own, isolated from the
  live C:\9to5 instance. The live bot and this one share nothing but the Discord
  API (different token, different app, different server/channel).

  This never reads or writes the real C:\9to5\.env.

.PARAMETER Check
  Validate config and print what would launch, without starting the bot.
#>
param([switch]$Check)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot          # worktree root (scripts/ -> ..)
$envFile = Join-Path $root ".env.nightclaw2"
$logDir = Join-Path $root "logs2"

if (-not (Test-Path $envFile)) {
    Write-Host "[nightclaw2] MISSING $envFile" -ForegroundColor Red
    Write-Host "  Copy .env.nightclaw2.template to .env.nightclaw2 and fill in a SECOND app's token."
    exit 1
}

# Parse KEY=VALUE (ignore blanks/comments) and export into this process.
$required = @("DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID")
$seen = @{}
foreach ($line in Get-Content $envFile) {
    $t = $line.Trim()
    if (-not $t -or $t.StartsWith("#")) { continue }
    $kv = $t -split "=", 2
    if ($kv.Count -ne 2) { continue }
    $k = $kv[0].Trim(); $v = $kv[1].Trim()
    if (-not $v) { continue }
    Set-Item -Path "Env:$k" -Value $v
    $seen[$k] = $true
}

foreach ($r in $required) {
    if (-not $seen[$r] -or [string]::IsNullOrWhiteSpace((Get-Item "Env:$r" -ErrorAction SilentlyContinue).Value)) {
        Write-Host "[nightclaw2] $r is not set in $envFile" -ForegroundColor Red
        exit 1
    }
}
if ($env:DISCORD_BOT_TOKEN -eq "paste_second_bot_token_here") {
    Write-Host "[nightclaw2] DISCORD_BOT_TOKEN is still the placeholder — edit $envFile" -ForegroundColor Red
    exit 1
}

# Isolated log dir so this instance never writes the live 9to5.log.
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$env:NINE_TO_FIVE_LOG_DIR = $logDir

$tokLen = $env:DISCORD_BOT_TOKEN.Length
Write-Host "[nightclaw2] channel=$($env:DISCORD_CHANNEL_ID) guild=$($env:DISCORD_GUILD_ID) token_len=$tokLen"
Write-Host "[nightclaw2] cwd=$root  logdir=$logDir"

if ($Check) {
    Write-Host "[nightclaw2] --Check: config OK, not launching." -ForegroundColor Green
    exit 0
}

Set-Location $root
Write-Host "[nightclaw2] launching: python -m nightclaw  (Ctrl+C to stop)" -ForegroundColor Cyan
python -m nightclaw
