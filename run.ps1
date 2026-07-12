param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Component,

    [switch]$Json,

    [switch]$MostrarNavegador,

    [string]$Stores
)

$ErrorActionPreference = "Stop"
$SkillDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script = Join-Path $SkillDir "scripts\pc_price_finder.py"

. (Join-Path $SkillDir "scripts/resolve-python.ps1")
$Resolved = Resolve-PythonCommand -SkillDir $SkillDir
$PythonCommand = $Resolved.Command
$PythonArgs = @($Resolved.Arguments)

if ($Resolved.Source -eq "venv") {
    if ($IsWindows -or $env:OS -eq "Windows_NT") {
        $PythonCommand = Join-Path $SkillDir ".venv\Scripts\python.exe"
    } else {
        $PythonCommand = Join-Path $SkillDir ".venv/bin/python"
    }
    $PythonArgs = @()
}

$Arguments = @($Script, $Component)
if ($Json) { $Arguments += "--json" }
if ($MostrarNavegador) { $Arguments += "--mostrar-navegador" }
if ($Stores) { $Arguments += @("--stores", $Stores) }

& $PythonCommand @PythonArgs @Arguments
exit $LASTEXITCODE
