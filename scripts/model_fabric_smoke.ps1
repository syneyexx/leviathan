#Requires -Version 5.1
<#
.SYNOPSIS
  Adaptive Model Fabric hardware / placement smoke for LEVIATHAN.

.DESCRIPTION
  Queries the hardware inventory endpoint and asserts schema invariants:
  - aggregate physical VRAM is distinct from largest single-device VRAM
  - unknown metrics are not fabricated as zeros
  - device list is dynamic (0/1/N)

  Optional -PreflightModelId runs a non-destructive placement preflight.

.PARAMETER BaseUrl
  LEVIATHAN API base URL (default http://127.0.0.1:8000)

.PARAMETER PreflightModelId
  Optional model id for dry-run placement preflight
#>
param(
  [string]$BaseUrl = "http://127.0.0.1:8000",
  [string]$PreflightModelId = ""
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
  Write-Host "FAIL: $Message" -ForegroundColor Red
  exit 1
}

function Ok([string]$Message) {
  Write-Host "OK: $Message" -ForegroundColor Green
}

Write-Host "LEVIATHAN Adaptive Model Fabric smoke"
Write-Host "BaseUrl: $BaseUrl"

try {
  $hw = Invoke-RestMethod -Uri "$BaseUrl/api/models/hardware" -Method Get
} catch {
  Fail "hardware endpoint unreachable: $_"
}

if (-not $hw.hardware) { Fail "missing hardware object" }
$h = $hw.hardware

if (-not $h.truth -or -not $h.truth.aggregateIsNotContiguous) {
  Fail "truth.aggregateIsNotContiguous must be true"
}
Ok "aggregateIsNotContiguous truth flag present"

$deviceCount = 0
if ($h.devices) { $deviceCount = @($h.devices).Count }
Write-Host "Physical accelerator count: $deviceCount"

$agg = $h.aggregatePhysicalVramBytes
$largest = $h.largestSingleDeviceTotalBytes
Write-Host ("Aggregate physical VRAM: {0}" -f $(if ($null -eq $agg) { "Unknown" } else { "$agg bytes" }))
Write-Host ("Largest device: {0}" -f $(if ($null -eq $largest) { "Unknown" } else { "$largest bytes" }))

if ($null -ne $agg -and $null -ne $largest -and $agg -lt $largest) {
  Fail "aggregate physical VRAM cannot be less than largest single device"
}

if ($deviceCount -ge 2 -and $null -ne $agg -and $null -ne $largest -and $agg -eq $largest) {
  Write-Host "WARN: multi-device inventory reports equal aggregate and largest — check telemetry" -ForegroundColor Yellow
}

foreach ($d in @($h.devices)) {
  if ($null -eq $d.stableDeviceId -or $d.stableDeviceId -eq "") {
    Fail "device missing stableDeviceId"
  }
  if ($null -ne $d.temperatureC -and $d.temperatureC -eq 0 -and $d.provenance -eq "UNKNOWN") {
    Fail "fabricated 0C temperature under UNKNOWN provenance"
  }
  Write-Host ("  - {0} ord={1} total={2} free={3} temp={4}" -f `
    $d.name, $d.ordinal, $d.totalVramBytes, $d.freeVramBytes, `
    $(if ($null -eq $d.temperatureC) { "Unknown" } else { $d.temperatureC }))
}

$hostMem = $h.hostMemory
if ($hostMem) {
  Write-Host ("Host RAM available: {0} / total {1} pressure={2}" -f `
    $hostMem.availableBytes, $hostMem.totalBytes, $hostMem.pressure)
}

$resCount = 0
if ($hw.reservations) { $resCount = @($hw.reservations).Count }
Write-Host "Held reservations: $resCount"

if ($PreflightModelId) {
  try {
    $pre = Invoke-RestMethod -Uri "$BaseUrl/api/models/$PreflightModelId/placement-preflight" `
      -Method Post -ContentType "application/json" -Body "{}"
  } catch {
    Fail "placement preflight failed: $_"
  }
  if (-not $pre.truth -or -not $pre.truth.didNotLoadModel -or -not $pre.truth.didNotReserve) {
    Fail "preflight must be non-destructive"
  }
  Write-Host ("Preflight feasible={0}" -f $pre.feasible)
  Ok "placement preflight non-destructive"
}

Ok "model fabric smoke passed"
exit 0
