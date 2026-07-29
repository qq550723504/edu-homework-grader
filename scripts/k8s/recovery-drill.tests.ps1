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
        $source | Should -Match 'initContainers:'
        $source | Should -Match 'rclone/rclone:1\.71\.0'
        $source | Should -Match 'emptyDir:'
        $source | Should -Match 'pg_restore --clean --if-exists --no-owner'
    }

    It 'does not delete production resources or print secrets' {
        $source = Get-Content -Raw -LiteralPath $scriptPath

        $source | Should -Not -Match 'delete\s+(statefulset|pod)\s+postgres\b'
        $source | Should -Not -Match '(?i)Write-(Host|Output).*?(SECRET|PASSWORD|ACCESS_KEY)'
        $source | Should -Match 'student_guardian_consents'
        $source | Should -Match 'audit_logs'
    }
}
