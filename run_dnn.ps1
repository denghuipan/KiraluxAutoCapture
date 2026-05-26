# Kiralux AutoCapture — uses DNN env Python directly (no `conda activate` needed)
$python = Join-Path $env:USERPROFILE "anaconda3\envs\DNN\python.exe"
$here   = $PSScriptRoot
$main   = Join-Path $here "main.py"
if (-not (Test-Path $python)) {
    Write-Error "Python not found: $python"
    exit 1
}
Set-Location $here
& $python $main
