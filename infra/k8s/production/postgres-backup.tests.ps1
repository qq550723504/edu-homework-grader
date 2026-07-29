Describe 'postgres-backup manifest' {
    BeforeAll {
        $manifestPath = Join-Path $PSScriptRoot 'postgres-backup.yaml'
        $manifest = Get-Content -Raw -LiteralPath $manifestPath
    }

    It 'runs weekly in the pilot timezone without overlap' {
        $manifest | Should -Match '(?m)^kind:\s*CronJob\s*$'
        $manifest | Should -Match '(?m)^\s{2}name:\s*postgres-backup\s*$'
        $manifest | Should -Match '(?m)^\s{2}schedule:\s*"15 3 \* \* 0"\s*$'
        $manifest | Should -Match '(?m)^\s{2}timeZone:\s*Asia/Singapore\s*$'
        $manifest | Should -Match '(?m)^\s{2}concurrencyPolicy:\s*Forbid\s*$'
    }

    It 'creates a verified custom dump and limits cleanup to the backup prefix' {
        $manifest | Should -Match 'pg_dump.*--format=custom'
        $manifest | Should -Match 'sha256sum.*edu_grader.dump'
        $manifest | Should -Match 'provider = TencentCOS'
        $manifest | Should -Match 'edu-homework-grader/postgres/v1/'
        $manifest | Should -Match 'rclone delete.*--min-age 14d'
        $manifest | Should -Match 'backup_timestamp='
    }

    It 'keeps database and COS Secret access separate' {
        $manifest | Should -Match 'name:\s*edu-grader-runtime\s*\r?\n\s*key:\s*POSTGRES_PASSWORD'
        $manifest | Should -Match 'name:\s*edu-grader-backup-cos'
        $manifest | Should -Not -Match 'task-processor'
        $manifest | Should -Not -Match '(?i)(AKID|SECRET_ACCESS_KEY:\s*[^$])'
    }
}
