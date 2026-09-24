<#
.SYNOPSIS
  Chat boundary smoke: exact-output APPEL must not leak Brain/medical/[tier2] text.

.EXAMPLE
  .\scripts\chat_boundary_smoke.ps1 -Iterations 100
#>
param(
  [int]$Iterations = 1,
  [string]$BaseUrl = "http://127.0.0.1:8787",
  [string]$ExactPrompt = "Antwoord alleen met het woord: APPEL"
)

$ErrorActionPreference = "Stop"
$failed = 0
$medicalAnchors = @(
  "A 60-year-old male presents with severe depressive symptoms",
  "A 7-year-old boy presents with progressive fatigue",
  "[tier2]"
)

function New-Conversation {
  $resp = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/conversations" -ContentType "application/json" -Body "{}"
  return $resp.conversation.id
}

function Invoke-Chat([string]$ConversationId, [string]$Message) {
  $body = @{
    message = $Message
    conversation_id = $ConversationId
    stream = $false
  } | ConvertTo-Json
  return Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/chat" -ContentType "application/json" -Body $body
}

Write-Host "LEVIATHAN chat boundary smoke — iterations=$Iterations base=$BaseUrl"

for ($i = 1; $i -le $Iterations; $i++) {
  try {
    $cid = New-Conversation
    $result = Invoke-Chat -ConversationId $cid -Message $ExactPrompt
    $answer = [string]$result.assistant_message.content
    $answer = $answer.Trim()

    if ($answer -ne "APPEL") {
      Write-Host "[FAIL] iter=$i expected APPEL got: $answer"
      $failed++
      continue
    }

    foreach ($anchor in $medicalAnchors) {
      if ($answer.Contains($anchor)) {
        Write-Host "[FAIL] iter=$i medical/tier leakage: $anchor"
        $failed++
        continue
      }
    }

    if ($answer -match '(?m)^(user|assistant)\s*:') {
      Write-Host "[FAIL] iter=$i fake role continuation in answer"
      $failed++
      continue
    }

    if ($null -ne $result.retrieval_gate -and $result.retrieval_gate.use_knowledge -eq $true) {
      Write-Host "[FAIL] iter=$i retrieval_gate.use_knowledge unexpectedly true"
      $failed++
      continue
    }

    Write-Host "[OK] iter=$i conversation=$cid answer=APPEL"
  }
  catch {
    Write-Host "[FAIL] iter=$i exception: $($_.Exception.Message)"
    $failed++
  }
}

if ($failed -gt 0) {
  Write-Host "FAILED: $failed / $Iterations"
  exit 1
}

Write-Host "PASSED: $Iterations / $Iterations"
exit 0
