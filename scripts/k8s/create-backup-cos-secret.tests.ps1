Describe 'create-backup-cos-secret' {
    BeforeAll {
        $scriptPath = Join-Path $PSScriptRoot 'create-backup-cos-secret.ps1'
    }

    It 'requires explicit confirmation before it invokes kubectl' {
        Mock kubectl { throw 'kubectl must not run' }

        {
            & $scriptPath `
                -Bucket 'backup-bucket' `
                -Endpoint 'https://cos.example.test' `
                -Region 'na-ashburn'
        } | Should -Throw -ExpectedMessage '*-ConfirmBackupCredential*'

        # The mocked command throws if called, so the expected confirmation error
        # proves validation completed before any Kubernetes invocation.
    }

    It 'rejects a non-HTTPS endpoint before it invokes kubectl' {
        Mock kubectl { throw 'kubectl must not run' }

        {
            & $scriptPath `
                -Bucket 'backup-bucket' `
                -Endpoint 'http://cos.example.test' `
                -Region 'na-ashburn' `
                -ConfirmBackupCredential
        } | Should -Throw -ExpectedMessage '*HTTPS*'

        # The mocked command throws if called, so the expected endpoint error
        # proves validation completed before any Kubernetes invocation.
    }

    It 'uses prompt-only credential handling and does not emit credential values' {
        $source = Get-Content -Raw -LiteralPath $scriptPath

        $source | Should -Match 'Read-Host.*AsSecureString'
        $source | Should -Match 'kubectl.*create.*secret.*generic'
        $source | Should -Not -Match 'Write-(Host|Output).*?(ACCESS|SECRET|PASSWORD|CREDENTIAL)'
    }
}
