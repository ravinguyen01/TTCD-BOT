$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$testDatabase = 'classbot_acceptance_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
if ($testDatabase -notmatch '^classbot_acceptance_[0-9_]+$') { throw 'Invalid acceptance database name' }
$created = $false
Push-Location -LiteralPath $projectRoot
try {
    docker compose up -d db --wait
    if ($LASTEXITCODE -ne 0) { throw 'Database is not ready' }
    docker compose --profile online build bot --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    docker compose exec -T db createdb -U classbot $testDatabase
    if ($LASTEXITCODE -ne 0) { throw 'Could not create isolated test database' }
    $created = $true
    $testMount = "${projectRoot}/tests:/app/tests:ro"
    $testUrl = "postgresql://classbot:local_only_change_me@db:5432/$testDatabase"
    docker compose --profile online run --rm --no-deps -v $testMount -e "DATABASE_URL=$testUrl" bot python /app/tests/run_acceptance.py
    if ($LASTEXITCODE -ne 0) { throw 'Acceptance failed' }
} finally {
    if ($created) {
        docker compose exec -T db dropdb -U classbot --if-exists $testDatabase
        if ($LASTEXITCODE -ne 0) { Write-Warning "Could not remove test database $testDatabase" }
    }
    Pop-Location
}
