Describe 'recovery-drill' {
    BeforeAll {
        $scriptPath = Join-Path $PSScriptRoot 'recovery-drill.ps1'
    }

    It 'requires confirmation before it invokes Kubernetes' {
        Mock kubectl { throw 'kubectl must not run' }

        {
            & $scriptPath -BackupTimestamp '20260729T031500Z'
        } | Should -Throw -ExpectedMessage '*-ConfirmRecovery*'
    }

    It 'rejects a non-UTC timestamp before it invokes Kubernetes' {
        Mock kubectl { throw 'kubectl must not run' }

        {
            & $scriptPath -BackupTimestamp '2026-07-29' -ConfirmRecovery
        } | Should -Throw -ExpectedMessage '*BackupTimestamp*yyyyMMddTHHmmssZ*'
    }

    It 'uses one isolated recovery Pod with an rclone init container' {
        $source = Get-Content -Raw -LiteralPath $scriptPath

        $source | Should -Match 'postgres-recovery-\$BackupTimestamp'
        $source | Should -Match 'postgres-recovery-\$BackupTimestamp"\.ToLowerInvariant\(\)'
        $source | Should -Match 'initContainers:'
        $source | Should -Match 'rclone/rclone:1\.71\.0'
        $source | Should -Match 'emptyDir:'
        $source | Should -Match 'pg_restore --clean --if-exists --no-owner'
        $source | Should -Match 'args:'
        $source | Should -Not -Match '(?m)^      command:\s*\r?\n        - postgres$'
        $source | Should -Match 'access_key_id = `\$COS_S3_ACCESS_KEY_ID'
        $source | Should -Not -Match 'access_key_id = \\\$COS_S3_ACCESS_KEY_ID'
    }

    It 'does not delete production resources or print secrets' {
        $source = Get-Content -Raw -LiteralPath $scriptPath

        $source | Should -Not -Match 'delete\s+(statefulset|pod)\s+postgres\b'
        $source | Should -Not -Match '(?i)Write-(Host|Output).*?(SECRET|PASSWORD|ACCESS_KEY)'
        $source | Should -Match 'student_guardian_consents'
        $source | Should -Match 'audit_logs'
    }
}

Describe 'PostgreSQL COS backup documentation' {
    It 'documents the confirmation-gated backup and recovery workflow without credentials' {
        $documentPath = Join-Path $PSScriptRoot '..\..\docs\operations\postgres-cos-backup-recovery.md'
        $document = Get-Content -Raw -LiteralPath $documentPath

        $document | Should -Match '-ConfirmBackupCredential'
        $document | Should -Match '-ConfirmRecovery'
        $document | Should -Match '-BackupTimestamp'
        $document | Should -Match '-KeepRecoveryArtifacts'
        $document | Should -Match 'postgres-backup'
        $document | Should -Match '14 days'
        $document | Should -Match 'edu-homework-grader/postgres/'
        $document | Should -Match 'Build API migration image'
        $document | Should -Match 'api-migration-image-digest'
        $document | Should -Match '@sha256'
        $document | Should -Match "postgres-backup-manual-' \+ \(Get-Date -AsUTC -Format 'yyyyMMddHHmmss'\)"
        $document | Should -Not -Match "postgres-backup-manual-\$\(Get-Date -AsUTC -Format 'yyyyMMddTHHmmssZ'\)"
        $document | Should -Not -Match 'AKID'
        $document | Should -Not -Match 'SECRET_ACCESS_KEY='
        $document | Should -Not -Match 'POSTGRES_PASSWORD='
    }
}
