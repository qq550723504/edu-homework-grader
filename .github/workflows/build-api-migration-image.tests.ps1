Describe 'build API migration image workflow' {
    BeforeAll {
        $workflowPath = Join-Path $PSScriptRoot 'build-api-migration-image.yml'
        $workflow = Get-Content -Raw -LiteralPath $workflowPath
    }

    It 'builds only a validated API revision without deployment access' {
        $workflow | Should -Match 'workflow_dispatch:'
        $workflow | Should -Match '(?m)^  contents: read$'
        $workflow | Should -Match '(?m)^  packages: write$'
        $workflow | Should -Match '\[\[ "\$SOURCE_SHA" =~ \^\[0-9a-f\]\{40\}\$ \]\]'
        $workflow | Should -Match 'file: apps/api/Dockerfile'
        $workflow | Should -Match 'ghcr\.io/\$\{\{ github\.repository_owner \}\}/edu-homework-grader-api:\$\{\{ inputs\.source_sha \}\}'
        $workflow | Should -Not -Match '(?i)kubectl|deploy-production|kubeconfig|environment:'
    }

    It 'publishes a validated digest artifact for the migration runner' {
        $workflow | Should -Match 'api-migration-image-digest'
        $workflow | Should -Match 'retention-days: 1'
        $workflow | Should -Match 'sha256:\[0-9a-f\]\{64\}'
        $workflow | Should -Match 'GITHUB_STEP_SUMMARY'
    }
}
