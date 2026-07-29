Describe 'build API migration image workflow' {
    BeforeAll {
        $workflowPath = Join-Path $PSScriptRoot 'build-api-migration-image.yml'
        $workflow = Get-Content -Raw -LiteralPath $workflowPath
    }

    It 'builds only a validated API revision without deployment access' {
        $workflow | Should -Match 'workflow_dispatch:'
        $workflow | Should -Match 'pull_request:'
        $workflow | Should -Match 'types: \[labeled\]'
        $workflow | Should -Match "github\.event\.label\.name == 'build-migration-image'"
        $workflow | Should -Match 'github\.event\.pull_request\.head\.repo\.full_name == github\.repository'
        $workflow | Should -Match '(?m)^  contents: read$'
        $workflow | Should -Match '(?m)^  packages: write$'
        $workflow | Should -Match '\[\[ "\$SOURCE_SHA" =~ \^\[0-9a-f\]\{40\}\$ \]\]'
        $workflow | Should -Match 'file: apps/api/Dockerfile'
        $workflow | Should -Match 'ghcr\.io/\$\{\{ github\.repository_owner \}\}/edu-homework-grader-api:\$\{\{ env\.SOURCE_SHA \}\}'
        $workflow | Should -Not -Match '(?i)kubectl|deploy-production|kubeconfig|environment:'
    }

    It 'uses the labeled pull request head SHA as the bootstrap build source' {
        $workflow | Should -Match 'PULL_REQUEST_SOURCE_SHA: \$\{\{ github\.event\.pull_request\.head\.sha \}\}'
        $workflow | Should -Match 'SOURCE_SHA="\$PULL_REQUEST_SOURCE_SHA"'
    }

    It 'publishes a validated digest artifact for the migration runner' {
        $workflow | Should -Match 'api-migration-image-digest'
        $workflow | Should -Match 'retention-days: 1'
        $workflow | Should -Match 'sha256:\[0-9a-f\]\{64\}'
        $workflow | Should -Match 'GITHUB_STEP_SUMMARY'
    }
}
