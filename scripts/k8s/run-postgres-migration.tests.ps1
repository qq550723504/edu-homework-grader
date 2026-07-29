Describe 'run-postgres-migration' {
    BeforeAll {
        $scriptPath = Join-Path $PSScriptRoot 'run-postgres-migration.ps1'
        $source = Get-Content -Raw -LiteralPath $scriptPath
    }

    It 'requires explicit confirmation and an immutable API image digest' {
        $source | Should -Match 'ConfirmMigration'
        $source | Should -Match 'image reference must include an immutable sha256 digest'
        $source | Should -Match '@sha256:\[0-9a-f\]\{64\}'
    }

    It 'runs one bounded Alembic Job with only the database URL secret' {
        $source | Should -Match 'kind: Job'
        $source | Should -Match "\$jobName = 'postgres-migrate-'"
        $source | Should -Match 'name: \$jobName'
        $source | Should -Match 'activeDeadlineSeconds: 900'
        $source | Should -Match 'backoffLimit: 0'
        $source | Should -Match 'python", "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"'
        $source | Should -Match 'name: edu-grader-runtime'
        $source | Should -Match 'key: DATABASE_URL'
        $source | Should -Not -Match 'envFrom:'
    }

    It 'waits for completion and records only the Alembic revision' {
        $source | Should -Match 'wait --for=condition=complete'
        $source | Should -Match 'select version_num from alembic_version'
        $source | Should -Not -Match 'POSTGRES_PASSWORD'
    }
}
