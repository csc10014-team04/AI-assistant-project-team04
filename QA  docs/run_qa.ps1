<#
.SYNOPSIS
  One command to run every QA check of the project the right way (each suite in its own process).

.DESCRIPTION
  Why a script: the repo has two conftest.py files; pytest crashes with "cannot import name 'class_row' from 'conftest'"
  when both folders are collected in one run. This script runs each suite separately, picks the right Python,
  skips the Kivy tests when Kivy is not installed, and prints one summary table.

.EXAMPLE
  .\run_qa.ps1                       # fast: main suite + QA suites + NLU rule evaluation
  .\run_qa.ps1 -Coverage             # also measure coverage
  .\run_qa.ps1 -Lint                 # also ruff / mypy / bandit / radon (needs: pip install -r requirements-qa.txt)
  .\run_qa.ps1 -Bench                # also run the latency benchmark (about 3-4 minutes)
  .\run_qa.ps1 -All                  # everything above
#>
param(
    [switch]$Coverage,
    [switch]$Lint,
    [switch]$Bench,
    [switch]$All,
    [int]$BenchRuns = 300
)

$ErrorActionPreference = "Continue"
$QaDir = $PSScriptRoot
$Root = Split-Path -Parent $QaDir
$Be = Join-Path $Root "sourceCode\BE"
$LogDir = Join-Path $QaDir "last_run"   # full output of every suite is saved here (attach to bug reports)
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
if ($All) { $Coverage = $true; $Lint = $true; $Bench = $true }

# ---------------------------------------------------------------- pick a Python
$candidates = @(
    (Join-Path $Root ".venv\Scripts\python.exe"),
    (Join-Path $Be ".venv\Scripts\python.exe")
)
$Py = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Py) { $Py = "python" }
$ver = (& $Py --version) 2>&1 | Out-String
Write-Host "Python : $Py  ($($ver.Trim()))" -ForegroundColor Cyan
if ($ver -match "3\.(1[4-9])") { Write-Host "WARNING: Python 3.14+ cannot install Kivy; use 3.12 or 3.13 for FE tests." -ForegroundColor Yellow }
Write-Host "Repo   : $Root`n"

function Test-Import([string]$module) {
    & $Py -c "import $module" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

$results = New-Object System.Collections.Generic.List[object]

function Add-Result($name, $code, $text) {
    $n = @{ passed = 0; failed = 0; skipped = 0; xfailed = 0; errors = 0 }
    foreach ($k in @("passed", "failed", "skipped", "xfailed")) {
        if ($text -match "(\d+) $k") { $n[$k] = [int]$Matches[1] }
    }
    if ($text -match "(\d+) errors?\b") { $n.errors = [int]$Matches[1] }
    $results.Add([pscustomobject]@{
        Suite = $name; Passed = $n.passed; Failed = $n.failed; Errors = $n.errors
        Skipped = $n.skipped; XFail = $n.xfailed; Exit = $code
    })
}

function Run-Pytest([string]$name, [string[]]$pytestArgs, [string]$cwd = $Root) {
    Write-Host ">> $name" -ForegroundColor Green
    Push-Location $cwd
    try {
        $env:PYTHONIOENCODING = "utf-8"
        $text = & $Py -m pytest @pytestArgs -q -rfs --tb=line -p no:cacheprovider 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally { Pop-Location }
    $safe = ($name -replace "[^\w\-]+", "_").Trim("_")
    Set-Content -Path (Join-Path $LogDir "$safe.log") -Value $text -Encoding UTF8
    $tail = ($text -split "`r?`n" | Where-Object { $_ -match "passed|failed|skipped|error|no tests ran" } | Select-Object -Last 1)
    Write-Host "   $tail"
    $skipLines = $text -split "`r?`n" | Where-Object { $_ -match "^SKIPPED .*(could not import|No module)" }
    foreach ($s in $skipLines) { Write-Host "   $($s.Trim())" -ForegroundColor Yellow }
    if ($text -notmatch "\d+ (passed|failed|skipped|error)" -and $text -notmatch "no tests ran") {
        Write-Host "   !! pytest ended without a summary (process crashed or was killed). Exit code $code." -ForegroundColor Red
        $code = if ($code) { $code } else { 99 }
    }
    Add-Result $name $code $text
    return $text
}

# ---------------------------------------------------------------- 1. main suite (tests/ at the repo root, without the Kivy tests)
# The Kivy (FE) tests open real windows and can crash the whole Python process, so they run in their own process (step 1b).
$feTests = @("tests/test_fe_notifier.py", "tests/test_fe_event_store.py", "tests/test_fe_fallback.py", "tests/test_frontend.py")
$mainArgs = @("tests") + ($feTests | ForEach-Object { "--ignore=$_" })
if ($Coverage) {
    if (Test-Import "pytest_cov") { $mainArgs += @("--cov=sourceCode/BE", "--cov-branch", "--cov-report=term:skip-covered") }
    else { Write-Host "pytest-cov missing -> run: pip install -r `"QA  docs\requirements-qa.txt`"" -ForegroundColor Yellow }
}
if (-not (Test-Import "bs4")) { Write-Host "beautifulsoup4 missing -> KB tests will be SKIPPED (pip install beautifulsoup4)" -ForegroundColor Yellow }
$mainText = Run-Pytest "main suite (tests/)" $mainArgs
if ($Coverage) { ($mainText -split "`r?`n" | Where-Object { $_ -match "^TOTAL" }) | ForEach-Object { Write-Host "   $_" } }

# ---------------------------------------------------------------- 1b. FE (Kivy) tests, isolated
if (Test-Import "kivy") {
    $env:KIVY_NO_ARGS = "1"
    Run-Pytest "FE tests (Kivy)" $feTests | Out-Null
} else {
    Write-Host ">> FE tests (Kivy): SKIPPED - Kivy is not installed (needs Python 3.12/3.13 + requirements-fullStack.txt)" -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 2. QA suites that live outside tests/ (wherever they were placed)
foreach ($f in @("test_crypto.py", "test_split_task.py")) {
    $path = @((Join-Path $Root $f), (Join-Path $QaDir $f)) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($path) { Run-Pytest "QA: $f" @($path) | Out-Null }
}

# ---------------------------------------------------------------- 3. backend-side tests (separate session: it has its own conftest.py)
if (Test-Path (Join-Path $Be "tests\test_assistant_reminders_api.py")) {
    Run-Pytest "backend tests (sourceCode/BE/tests)" @("sourceCode/BE/tests") | Out-Null
}

# ---------------------------------------------------------------- 4. NLU rule-based evaluation
Write-Host ">> NLU evaluation (rules only; the LLM mode needs vLLM: python tools/eval_nlu.py)" -ForegroundColor Green
Push-Location $Be
$env:PYTHONIOENCODING = "utf-8"
$nluText = & $Py "tools/eval_nlu.py" "--rules" 2>&1 | Out-String
$nluCode = $LASTEXITCODE
Pop-Location
try {
    $j = $nluText | ConvertFrom-Json
    Write-Host ("   n={0}  intent={1}%  duration={2}%  date_hint={3}%  bad_dates={4}" -f $j.n, $j.intent_acc_pct, $j.duration_acc_pct, $j.hint_acc_pct, $j.bad_dates)
    Write-Host "   (schema_adherence is meaningless in --rules mode)" -ForegroundColor DarkGray
} catch { Write-Host "   could not read NLU result:`n$nluText" -ForegroundColor Red }

# ---------------------------------------------------------------- 5. optional: lint / static analysis
if ($Lint) {
    Write-Host "`n>> static analysis" -ForegroundColor Green
    $ex = "sourceCode/BE/.venv"
    Push-Location $Root
    if (Test-Import "ruff") { $o = & $Py -m ruff check sourceCode/BE --exclude $ex --statistics 2>&1 | Out-String; Write-Host ("   ruff   : " + (($o -split "`r?`n" | Where-Object { $_ -match "Found|All checks" } | Select-Object -First 1))) }
    if (Test-Import "mypy") { $o = & $Py -m mypy sourceCode/BE --ignore-missing-imports --exclude '\.venv|/tests/' 2>&1 | Out-String; Write-Host ("   mypy   : " + (($o -split "`r?`n" | Where-Object { $_ -match "Found|Success" } | Select-Object -First 1))) }
    if (Test-Import "bandit") { $o = & $Py -m bandit -r sourceCode/BE -x "sourceCode/BE/.venv,sourceCode/BE/tests" -q 2>&1 | Out-String; $m = [regex]::Match($o, "High: (\d+)"); Write-Host ("   bandit : high=" + $m.Groups[1].Value + "  (see full report: python -m bandit -r sourceCode/BE ...)") }
    if (Test-Import "radon") { $o = & $Py -m radon cc -s -a sourceCode/BE/services sourceCode/BE/routers 2>&1 | Out-String; Write-Host ("   radon  : " + (($o -split "`r?`n" | Where-Object { $_ -match "Average complexity" } | Select-Object -First 1))) }
    else { Write-Host "   analysis tools missing -> pip install -r `"QA  docs\requirements-qa.txt`"" -ForegroundColor Yellow }
    Pop-Location
}

# ---------------------------------------------------------------- 6. optional: latency benchmark
if ($Bench) {
    $benchScript = @((Join-Path $Root "bench_pure.py"), (Join-Path $QaDir "bench_pure.py"), (Join-Path $Root "tests\bench_pure.py")) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($benchScript) {
        Write-Host "`n>> latency benchmark ($BenchRuns runs; keep the laptop plugged in and other programs closed)" -ForegroundColor Green
        Push-Location $Be
        $out = Join-Path $QaDir "bench_results.json"
        & $Py $benchScript --runs $BenchRuns --json $out 2>&1 | ForEach-Object { Write-Host "   $_" }
        Pop-Location
    } else { Write-Host "bench_pure.py not found" -ForegroundColor Yellow }
}

# ---------------------------------------------------------------- summary
Write-Host "`n================ QA SUMMARY ================" -ForegroundColor Cyan
$results | Format-Table -AutoSize | Out-String | Write-Host
$bad = @($results | Where-Object { $_.Failed -gt 0 -or $_.Errors -gt 0 -or $_.Exit -ge 2 })
if ($bad.Count -gt 0) {
    Write-Host "Suites with failures: $($bad.Suite -join ', ')" -ForegroundColor Red
    Write-Host "Full logs: $LogDir  |  failing test names: Select-String -Path `"$LogDir\*.log`" -Pattern '^FAILED'"
    Write-Host "Known failures and their likely causes are listed in QA_README.md (section 'Known issues')."
    exit 1
}
Write-Host "No failing suite." -ForegroundColor Green
exit 0
