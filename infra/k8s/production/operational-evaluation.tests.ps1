Describe 'operational evaluation production isolation' {
    It 'binds only the API control plane and retention worker to Kubernetes roles' {
        $manifest = Get-Content (Join-Path $PSScriptRoot 'operational-evaluation.yaml') -Raw

        $manifest | Should -Match 'kind:\s*RoleBinding[\s\S]*?name:\s*operational-evaluation-api'
        $manifest | Should -Match 'kind:\s*RoleBinding[\s\S]*?name:\s*operational-evaluation-retention'
        $manifest | Should -Not -Match 'subjects:\s*\r?\n\s*- kind: ServiceAccount\s*\r?\n\s*name:\s*operational-evaluation-executor'
    }

    It 'uses a default-deny policy before limited executor egress and retains runs for thirty days' {
        $manifest = Get-Content (Join-Path $PSScriptRoot 'operational-evaluation.yaml') -Raw

        $manifest | Should -Match 'name:\s*operational-evaluation-default-deny'
        $manifest | Should -Match 'name:\s*operational-evaluation-executor-egress'
        $manifest | Should -Match 'port:\s*53'
        $manifest | Should -Match 'name:\s*operational-evaluation-retention'
        $manifest | Should -Match 'backoffLimit:\s*0'
    }
}
