Describe 'bootstrap-operational-evaluation' {
    BeforeAll {
        $scriptPath = Join-Path $PSScriptRoot 'bootstrap-operational-evaluation.ps1'
    }

    It 'keeps evaluator database access read-only and out of command arguments' {
        $source = Get-Content -Raw $scriptPath

        $source | Should -Match 'GRANT SELECT ON TABLE public\.generation_jobs'
        $source | Should -Match 'public\.generated_question_review_decisions'
        $source | Should -Match 'public\.question_versions'
        $source | Should -Match 'has_table_privilege'
        $source | Should -Match 'NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS'
        $source | Should -Match "'--stdin'"
        $source | Should -Match '\$null = \$readerBootstrapSql \| & kubectl exec'
        $source | Should -Not -Match 'GRANT (INSERT|UPDATE|DELETE|ALL)'
        $source | Should -Not -Match 'ALTER DEFAULT PRIVILEGES'
    }

    It 'requires immutable executor image and trusted GitHub identity configuration' {
        $source = Get-Content -Raw $scriptPath

        $source | Should -Match 'GitHubOperationalEvaluationRepositoryId'
        $source | Should -Match 'GitHubOperationalEvaluationOwnerId'
        $source | Should -Match 'GitHubOperationalEvaluationWorkflowRef'
        $source | Should -Match '@sha256:'
        $source | Should -Match 'operational-evaluation-runtime'
        $source | Should -Not -Match 'Write-(Host|Output).*?(PASSWORD|HMAC|DATABASE_URL|TOKEN)'
    }

    It 'merges GitHub trust keys into the existing runtime secret' {
        $source = Get-Content -Raw $scriptPath

        $source | Should -Match '\$trustSecretPatch = @\{'
        $source | Should -Match 'GITHUB_OPERATIONAL_EVALUATION_AUDIENCE'
        $source | Should -Match 'ConvertTo-Json -Compress'
        $source | Should -Match 'kubectl patch secret \$RuntimeSecretName'
        $source | Should -Not -Match '''create'', ''secret'', ''generic'', \$RuntimeSecretName'
    }

    It 'bootstraps privileged evaluation infrastructure before release automation manages images' {
        $source = Get-Content -Raw $scriptPath

        $source | Should -Match 'operational-evaluation\.yaml'
        $source | Should -Match 'operational-evaluation-retention\.yaml'
        $source | Should -Match 'kubectl apply --server-side --force-conflicts --filename'
    }
}
