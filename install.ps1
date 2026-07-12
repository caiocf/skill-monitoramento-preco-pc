$ErrorActionPreference = "Stop"
$SkillDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $SkillDir

. (Join-Path $SkillDir "scripts/resolve-python.ps1")
$Resolved = Resolve-PythonCommand -SkillDir $SkillDir
$PythonCommand = $Resolved.Command
$PythonArgs = @($Resolved.Arguments)

if ($Resolved.Source -eq "venv") {
    if (-not (Test-Path (Join-Path $SkillDir ".venv"))) {
        & $PythonCommand @PythonArgs -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao criar o ambiente virtual local."
        }
    }
}

if ($Resolved.Source -eq "pyenv") {
    Write-Host "Usando interpretador do pyenv: $PythonCommand"
} elseif ($Resolved.Source -eq "venv") {
    Write-Host "Usando ambiente virtual local: $PythonCommand"
} else {
    Write-Host "Usando interpretador do sistema: $PythonCommand"
}

$PythonExec = $PythonCommand
if ($Resolved.Source -eq "venv") {
    if ($IsWindows -or $env:OS -eq "Windows_NT") {
        $PythonExec = Join-Path $SkillDir ".venv\Scripts\python.exe"
    } else {
        $PythonExec = Join-Path $SkillDir ".venv/bin/python"
    }
}

& $PythonExec -m pip install --upgrade pip
& $PythonExec -m pip install -r requirements.txt
& $PythonExec -m playwright install chromium

Write-Host "Instalação concluída. Teste com:"
Write-Host '.\run.ps1 "Ryzen 9 9950X3D"'
