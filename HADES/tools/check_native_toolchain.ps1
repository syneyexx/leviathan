[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$result = [ordered]@{
    platform = $env:OS
    cmake = $null
    ninja = $null
    msvc = $null
    ready = $false
}

foreach ($tool in @("cmake", "ninja", "cl")) {
    $command = Get-Command $tool -ErrorAction SilentlyContinue
    if ($tool -eq "cl") { $result.msvc = if ($command) { $command.Source } else { $null } }
    elseif ($tool -eq "cmake") { $result.cmake = if ($command) { $command.Source } else { $null } }
    else { $result.ninja = if ($command) { $command.Source } else { $null } }
}

if (-not $result.msvc) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $installation = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if ($installation) { $result.msvc = "Visual Studio C++ workload: $installation (run from Developer Command Prompt)" }
    }
}
$result.ready = [bool]($result.cmake -and $result.msvc)
$result | ConvertTo-Json -Depth 3
if (-not $result.ready) { exit 1 }
