Describe 'bootstrap-production-deployer' {
    BeforeAll {
        $scriptPath = Join-Path $PSScriptRoot 'bootstrap-production-deployer.ps1'
        $rbacPath = Join-Path $PSScriptRoot '..\..\infra\k8s\production\github-production-deployer-rbac.yaml'
    }

    It 'requires confirmation before creating a deploy credential' {
        { & $scriptPath -Repository 'qq550723504/edu-homework-grader' -WhatIf } |
            Should -Throw -ExpectedMessage '*-ConfirmProductionCredential*'
    }

    It 'does not print credentials' {
        $source = Get-Content -Raw $scriptPath
        $source | Should -Not -Match 'Write-(Host|Output).*?(TOKEN|KUBECONFIG|SECRET)'
        $source | Should -Match 'gh secret set KUBECONFIG_B64 --env production'
        $source | Should -Match 'kubectl create token'
    }

    It 'excludes Secrets and cluster-wide RBAC' {
        $manifest = Get-Content -Raw $rbacPath
        $manifest | Should -Match 'kind: ServiceAccount'
        $manifest | Should -Match 'kind: RoleBinding'
        $manifest | Should -Match 'deployments'
        $manifest | Should -Match 'cronjobs'
        $manifest | Should -Not -Match 'secrets'
        $manifest | Should -Not -Match 'ClusterRole'
    }
}
