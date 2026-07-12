function Resolve-PythonCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$SkillDir
    )

    $ErrorActionPreference = "Stop"

    $venvCandidates = @()
    if ($IsWindows -or $env:OS -eq "Windows_NT") {
        $venvCandidates += Join-Path $SkillDir ".venv\Scripts\python.exe"
        $venvCandidates += Join-Path $SkillDir ".venv\Scripts\python"
    } else {
        $venvCandidates += Join-Path $SkillDir ".venv/bin/python"
        $venvCandidates += Join-Path $SkillDir ".venv/bin/python3"
    }

    foreach ($candidate in $venvCandidates) {
        if (Test-Path $candidate) {
            return [pscustomobject]@{
                Command = $candidate
                Arguments = @()
                Source = "venv"
            }
        }
    }

    $pyenvCommand = Get-Command pyenv -ErrorAction SilentlyContinue
    if ($pyenvCommand) {
        $pyenvPython = (& pyenv which python 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -eq 0 -and $pyenvPython -and (Test-Path $pyenvPython)) {
            return [pscustomobject]@{
                Command = $pyenvPython
                Arguments = @()
                Source = "pyenv"
            }
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return [pscustomobject]@{
            Command = "python"
            Arguments = @()
            Source = "python"
        }
    }

    $python3Command = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python3Command) {
        return [pscustomobject]@{
            Command = "python3"
            Arguments = @()
            Source = "python3"
        }
    }

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        return [pscustomobject]@{
            Command = "py"
            Arguments = @("-3")
            Source = "py"
        }
    }

    throw "Nenhum interpretador Python foi encontrado. Instale o Python 3.11+ ou configure o pyenv antes de prosseguir."
}
