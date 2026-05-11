$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "python"

Push-Location $Here
try {
    & $Python -m PyInstaller `
        --onefile `
        --windowed `
        --clean `
        --exclude-module PyQt5 `
        --exclude-module PyQt6 `
        --exclude-module PySide2 `
        --exclude-module PySide6 `
        --exclude-module matplotlib `
        --exclude-module IPython `
        --exclude-module notebook `
        --exclude-module jupyter `
        --exclude-module scipy `
        --exclude-module dask `
        --name "TobiiTSVExtractor" `
        "tobii_tsv_extractor.py"
}
finally {
    Pop-Location
}
