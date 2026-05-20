$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($py in @('py', 'python', 'python3')) {
    if (Get-Command $py -ErrorAction SilentlyContinue) {
        & $py -c "import sys; assert sys.version_info>=(3,8)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            & $py "$scriptDir\claude.py" @args
            exit $LASTEXITCODE
        }
    }
}
Write-Error "[claude-box] Python 3.8+ not found. Install it and ensure 'py', 'python', or 'python3' is on your PATH."
exit 1
