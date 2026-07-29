Describe 'operational evaluation production isolation' {
    It 'binds only the API control plane and retention worker to Kubernetes roles' {
        $manifest = Get-Content (Join-Path $PSScriptRoot 'operational-evaluation.yaml') -Raw

        $manifest | Should -Match 'kind:\s*RoleBinding[\s\S]*?name:\s*operational-evaluation-api'
        $manifest | Should -Match 'kind:\s*RoleBinding[\s\S]*?name:\s*operational-evaluation-retention'
        $manifest | Should -Not -Match 'subjects:\s*\r?\n\s*- kind: ServiceAccount\s*\r?\n\s*name:\s*operational-evaluation-executor'
    }

    It 'uses a default-deny policy before limited executor egress and retains runs for thirty days' {
        $infrastructure = Get-Content (Join-Path $PSScriptRoot 'operational-evaluation.yaml') -Raw
        $retentionWorkload = Get-Content (Join-Path $PSScriptRoot 'operational-evaluation-retention.yaml') -Raw

        $infrastructure | Should -Match 'name:\s*operational-evaluation-default-deny'
        $infrastructure | Should -Match 'name:\s*operational-evaluation-executor-egress'
        $infrastructure | Should -Match 'port:\s*53'
        $infrastructure | Should -Not -Match 'kind:\s*CronJob'
        $retentionWorkload | Should -Match 'name:\s*operational-evaluation-retention'
        $retentionWorkload | Should -Match 'backoffLimit:\s*0'
    }
}
