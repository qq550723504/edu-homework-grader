Describe 'bootstrap-production-deployer' {
    BeforeAll {
        $scriptPath = Join-Path $PSScriptRoot 'bootstrap-production-deployer.ps1'
        $rbacPath = Join-Path $PSScriptRoot '..\..\infra\k8s\production\github-production-deployer-rbac.yaml'
    }

    It 'requires confirmation before creating a deploy credential' {
        { & $scriptPath -WhatIf } |
            Should -Throw -ExpectedMessage '*-ConfirmProductionCredential*'
    }

    It 'rejects an arbitrary repository before invoking Kubernetes or GitHub' {
        Mock kubectl { throw 'kubectl must not run' }
        Mock gh { throw 'gh must not run' }

        { & $scriptPath -Repository 'attacker/repository' -ConfirmProductionCredential } |
            Should -Throw -ExpectedMessage '*Repository*'

        Assert-MockCalled kubectl -Times 0 -Exactly
        Assert-MockCalled gh -Times 0 -Exactly
    }

    It 'does not print credentials' {
        $source = Get-Content -Raw $scriptPath
        $source | Should -Not -Match 'Write-(Host|Output).*?(TOKEN|KUBECONFIG|SECRET)'
        $source | Should -Match 'gh secret set KUBECONFIG_B64 --env production'
        $source | Should -Match '--repo qq550723504/edu-homework-grader'
        $source | Should -Not -Match '\$Repository'
        $source | Should -Match 'kubectl create token'
    }

    It 'excludes Secrets and cluster-wide RBAC' {
        $manifest = Get-Content -Raw $rbacPath
        $manifest | Should -Match 'kind: ServiceAccount'
        $manifest | Should -Match 'kind: RoleBinding'
        $manifest | Should -Match 'deployments'
        $manifest | Should -Match 'cronjobs'
        $manifest | Should -Match 'endpoints'
        $manifest | Should -Not -Match 'secrets'
        $manifest | Should -Not -Match 'ClusterRole'
        $manifest | Should -Not -Match 'pods|pods/exec|pods/attach|pods/portforward'
        $manifest | Should -Not -Match 'resources:\s*\["\*"\]'
        $manifest | Should -Match 'resources: \["configmaps"\]\s*\r?\n\s*verbs: \["get", "list", "watch", "create", "patch", "update"\]'
        $manifest | Should -Match 'resourceNames: \["api", "grader", "web", "languagetool"\]'
    }

    It 'validates the issued token lifetime before uploading it' {
        $source = Get-Content -Raw $scriptPath
        $source | Should -Match 'MinimumTokenLifetimeHours'
        $source | Should -Match 'TokenRequest lifetime'
        $source.IndexOf('Assert-TokenLifetime') | Should -BeLessThan $source.IndexOf('gh secret set KUBECONFIG_B64')
        $source | Should -Not -Match 'insecure-skip-tls-verify'
    }
}
