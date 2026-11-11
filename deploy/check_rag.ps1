# deploy/check_rag.ps1 — проверка RAG-конвейера и поиска через API (шаги 0–4 из README-диагностики).
#
# Запуск (pwsh):
#   ./deploy/check_rag.ps1                            # адреса из KB_PUBLIC_URL в deploy/.env
#   ./deploy/check_rag.ps1 -BaseUrl http://1.2.3.4    # напрямую на VPS (Keycloak :8080, api :8001)
#   ./deploy/check_rag.ps1 -User petrov -Query "отчёт" -Insecure   # другой УЗ / самоподписанный TLS
#
# Шаги: токен (direct grant kb-cli) → test-connection → rag/status → /search (vector) → /rag/retrieve (hybrid).
param(
    [string]$BaseUrl = "",
    [string]$User = "ivanov",
    [string]$Query = "паркетные",
    [int]$K = 5,
    [switch]$Insecure
)

$ErrorActionPreference = "Stop"
if ($Insecure -and $PSVersionTable.PSVersion.Major -lt 6) {
    Write-Warning "-Insecure требует pwsh 7 (SkipCertificateCheck); продолжаю без него"
    $Insecure = $false
}
$common = @{}
if ($Insecure) { $common.SkipCertificateCheck = $true }

# .env лежит рядом со скриптом (deploy/)
$envmap = @{}
Get-Content (Join-Path $PSScriptRoot ".env") | ForEach-Object {
    if ($_ -match '^\s*(\w+)=(.*)$') { $envmap[$Matches[1]] = $Matches[2].Trim() }
}

# Адреса: https → всё за nginx (/auth, /api — порты 8080/8001 закрыты);
# http → прямые порты (как в seed_demo.py)
if (-not $BaseUrl) { $BaseUrl = $envmap["KB_PUBLIC_URL"] }
if (-not $BaseUrl) { throw "Задайте -BaseUrl или KB_PUBLIC_URL в deploy/.env" }
$BaseUrl = $BaseUrl.TrimEnd("/")
$tls = $BaseUrl -like "https://*"
$kc = if ($tls) { "$BaseUrl/auth/realms/kb/protocol/openid-connect/token" }
      else      { "$BaseUrl:8080/realms/kb/protocol/openid-connect/token" }
$api = if ($tls) { "$BaseUrl/api/v1" } else { "$BaseUrl:8001/api/v1" }
Write-Host "Стенд: $BaseUrl (Keycloak: $kc)"

# --- [1/4] токен ---
$tok = (Invoke-RestMethod -Method Post -Uri $kc -Body @{
    grant_type    = "password"
    client_id     = "kb-cli"
    client_secret = $envmap["KB_CLI_CLIENT_SECRET"]
    username      = $User
    password      = $envmap["KB_TEST_PASSWORD"]
} @common).access_token
$h = @{ Authorization = "Bearer $tok" }
Write-Host "[1/4] токен: ok (пользователь: $User)"

# --- [2/4] embedding-провайдер ---
$conn = Invoke-RestMethod -Method Post -Uri "$api/admin/rag/test-connection" -Headers $h @common
Write-Host ("[2/4] провайдер: ok, model={0} dim={1}" -f $conn.model, $conn.dim)

# --- [3/4] статус индексации ---
function _cnt($c, $k) { if ($c.PSObject.Properties.Name -contains $k) { [int]$c.$k } else { 0 } }
$st = Invoke-RestMethod -Uri "$api/admin/rag/status" -Headers $h @common
$c = $st.counts
Write-Host ("[3/4] индексация: indexed={0} pending={1} error={2} none={3}; чанков: {4}" -f `
    (_cnt $c "indexed"), (_cnt $c "pending"), (_cnt $c "error"), (_cnt $c "none"), $st.total_chunks)
if ($st.problems.Count) {
    Write-Warning "Проблемные материалы (pending/error — очередь СА):"
    $st.problems | Format-Table id, name, state, stale -AutoSize
}

# --- [4/4] поиск: UI-выдача (vector, со score) + чанки (hybrid) ---
$q = [uri]::EscapeDataString($Query)
$s = Invoke-RestMethod -Uri "$api/search?q=$q&search_type=vector" -Headers $h @common
Write-Host ("[4/4] /search vector: всего={0}" -f $s.total)
$s.items | Select-Object name, score, status | Format-Table -AutoSize

$r = Invoke-RestMethod -Method Post -Uri "$api/rag/retrieve" -Headers $h @common `
    -ContentType "application/json" -Body (@{ query = $Query; k = $K; mode = "hybrid" } | ConvertTo-Json)
Write-Host ("POST /rag/retrieve hybrid (k={0}): {1} чанков" -f $K, $r.items.Count)
$r.items | Select-Object score, deep_link, @{n = "material"; e = { $_.material.name } } | Format-Table -AutoSize
