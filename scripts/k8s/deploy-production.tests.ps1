Describe 'deploy-production' {
BeforeAll {
    $script:scriptPath = Join-Path $PSScriptRoot 'deploy-production.ps1'
    $script:validSha = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    $originalKubeconfig = $env:KUBECONFIG
    $env:KUBECONFIG = Join-Path $TestDrive 'fake-kubeconfig'
    Set-Content -LiteralPath $env:KUBECONFIG -Value 'test-only'

    function kubectl {
        param(
            [Parameter(ValueFromRemainingArguments = $true)]
            [object[]]$Arguments
        )

        $joined = $Arguments -join ' '
        $global:DeployProductionTestState.KubectlCalls.Add($joined)

        if ($joined -eq 'get deployments api grader web languagetool --output json --namespace edu-homework-grader') {
            return @'
{"items":[
  {"metadata":{"name":"api"},"spec":{"template":{"spec":{"initContainers":[{"name":"migrate","image":"registry.example/migrate@sha256:old-migrate"}],"containers":[{"name":"api","image":"registry.example/api@sha256:old-api"}]}}}},
  {"metadata":{"name":"grader"},"spec":{"template":{"spec":{"containers":[{"name":"grader","image":"registry.example/grader@sha256:old-grader"}]}}}},
  {"metadata":{"name":"web"},"spec":{"template":{"spec":{"containers":[{"name":"web","image":"registry.example/web@sha256:old-web"}]}}}},
  {"metadata":{"name":"languagetool"},"spec":{"template":{"spec":{"containers":[{"name":"languagetool","image":"registry.example/languagetool@sha256:old-language"}]}}}}
]}
'@
        }

        if ($joined -eq 'get cronjob student-activation-expiry --output json --namespace edu-homework-grader') {
            return '{"metadata":{"name":"student-activation-expiry"},"spec":{"jobTemplate":{"spec":{"template":{"spec":{"containers":[{"name":"expire","image":"registry.example/api-cron@sha256:old-cron"}]}}}}}}'
        }

        if ($joined -match '^apply --server-side --filename ') {
            $global:DeployProductionTestState.ApplyCount++
            return 'applied'
        }

        if ($joined -match '^rollout status deployment/') {
            if ($global:DeployProductionTestState.RolloutFailuresRemaining -gt 0) {
                $global:DeployProductionTestState.RolloutFailuresRemaining--
                throw 'rollout timed out'
            }
            return 'rollout complete'
        }

        if ($joined -eq 'get endpoints api --output json --namespace edu-homework-grader') {
            if ($global:DeployProductionTestState.EndpointReady) {
                return '{"subsets":[{"addresses":[{"ip":"10.0.0.10"}]}]}'
            }
            return '{"subsets":[{"notReadyAddresses":[{"ip":"10.0.0.10"}]}]}'
        }

        throw "Unexpected kubectl call: $joined"
    }

    function kustomize {
        param(
            [Parameter(ValueFromRemainingArguments = $true)]
            [object[]]$Arguments
        )

        $joined = $Arguments -join ' '
        $global:DeployProductionTestState.KustomizeCalls.Add($joined)
        $global:DeployProductionTestState.KustomizeDirectories.Add((Get-Location).Path)

        if ($joined -eq 'build .') {
            $inputs = Get-ChildItem -Path (Get-Location).Path -Filter '*.yaml' -File |
                ForEach-Object { Get-Content -Raw -LiteralPath $_.FullName }
            $global:DeployProductionTestState.BuildInputs.Add(($inputs -join "`n---INPUT---`n"))
            return 'apiVersion: v1'
        }
        if ($joined -match '^edit set image ') {
            return
        }

        throw "Unexpected kustomize call: $joined"
    }

    function Invoke-WebRequest {
        param(
            [uri]$Uri,
            [string]$Method,
            [int]$MaximumRedirection,
            [int]$TimeoutSec
        )

        $global:DeployProductionTestState.PublicHealthCalls.Add([string]$Uri)
        return [pscustomobject]@{ StatusCode = 200 }
    }
}

AfterAll {
    $env:KUBECONFIG = $originalKubeconfig
}

BeforeEach {
    $global:DeployProductionTestState = @{
        KubectlCalls             = [System.Collections.Generic.List[string]]::new()
        KustomizeCalls           = [System.Collections.Generic.List[string]]::new()
        KustomizeDirectories     = [System.Collections.Generic.List[string]]::new()
        BuildInputs              = [System.Collections.Generic.List[string]]::new()
        PublicHealthCalls        = [System.Collections.Generic.List[string]]::new()
        ApplyCount               = 0
        RolloutFailuresRemaining = 0
        EndpointReady            = $true
    }
}

    It 'rejects mutable image references before kubectl runs' {
        { & $scriptPath -ImageSha 'latest' -SkipPublicHealthCheck } |
            Should -Throw '*40-character lower-case Git SHA*'

        $global:DeployProductionTestState.KubectlCalls | Should -HaveCount 0
    }

    It 'pins all managed images and verifies all four deployments and API endpoints' {
        & $scriptPath -ImageSha $validSha -SkipPublicHealthCheck

        $global:DeployProductionTestState.ApplyCount | Should -Be 1
        $global:DeployProductionTestState.KustomizeCalls |
            Should -Contain "edit set image ghcr.io/qq550723504/edu-homework-grader-api=ghcr.io/qq550723504/edu-homework-grader-api:$validSha"
        $global:DeployProductionTestState.KustomizeCalls |
            Should -Contain "edit set image ghcr.io/qq550723504/edu-homework-grader-grader=ghcr.io/qq550723504/edu-homework-grader-grader:$validSha"
        $global:DeployProductionTestState.KustomizeCalls |
            Should -Contain "edit set image ghcr.io/qq550723504/edu-homework-grader-web=ghcr.io/qq550723504/edu-homework-grader-web:$validSha"
        $global:DeployProductionTestState.KustomizeCalls |
            Should -Contain "edit set image ghcr.io/qq550723504/edu-homework-grader-languagetool=ghcr.io/qq550723504/edu-homework-grader-languagetool:$validSha"
        $global:DeployProductionTestState.KubectlCalls |
            Should -Contain 'get endpoints api --output json --namespace edu-homework-grader'
        @($global:DeployProductionTestState.KubectlCalls -match '^rollout status deployment/').Count |
            Should -Be 4
    }

    It 'restores the exact captured images after rollout failure' {
        $global:DeployProductionTestState.RolloutFailuresRemaining = 1

        { & $scriptPath -ImageSha $validSha -SkipPublicHealthCheck } |
            Should -Throw '*rollback succeeded*'

        $global:DeployProductionTestState.ApplyCount | Should -Be 2
        $renderedInputs = $global:DeployProductionTestState.BuildInputs -join "`n"
        $renderedInputs | Should -Match ([regex]::Escape('registry.example/migrate@sha256:old-migrate'))
        $renderedInputs | Should -Match ([regex]::Escape('registry.example/api@sha256:old-api'))
        $renderedInputs | Should -Match ([regex]::Escape('registry.example/grader@sha256:old-grader'))
        $renderedInputs | Should -Match ([regex]::Escape('registry.example/web@sha256:old-web'))
        $renderedInputs | Should -Match ([regex]::Escape('registry.example/languagetool@sha256:old-language'))
        $renderedInputs | Should -Match ([regex]::Escape('registry.example/api-cron@sha256:old-cron'))
    }

    It 'rolls back when the API Service has no ready endpoints' {
        $global:DeployProductionTestState.EndpointReady = $false

        { & $scriptPath -ImageSha $validSha -SkipPublicHealthCheck -EndpointTimeoutSeconds 0 } |
            Should -Throw '*rollback succeeded*'

        $global:DeployProductionTestState.ApplyCount | Should -Be 2
    }

    It 'reports a rollback failure separately from the release failure' {
        $global:DeployProductionTestState.RolloutFailuresRemaining = 2

        { & $scriptPath -ImageSha $validSha -SkipPublicHealthCheck } |
            Should -Throw '*rollback failed*'

        $global:DeployProductionTestState.ApplyCount | Should -Be 2
    }

    It 'checks the public HTTPS endpoint after in-cluster readiness' {
        & $scriptPath -ImageSha $validSha

        $global:DeployProductionTestState.PublicHealthCalls |
            Should -Contain 'https://edu.getkr.com/'
    }

    It 'removes every temporary release directory' {
        & $scriptPath -ImageSha $validSha -SkipPublicHealthCheck

        $global:DeployProductionTestState.KustomizeDirectories | Should -Not -BeNullOrEmpty
        foreach ($directory in $global:DeployProductionTestState.KustomizeDirectories) {
            Test-Path -LiteralPath $directory | Should -BeFalse
        }
    }

    It 'does not use pod access, query Secrets or print credential material' {
        $source = Get-Content -Raw $scriptPath

        $source | Should -Not -Match '(?i)\b(get|create|apply|patch|update|delete)\s+secrets?\b'
        $source | Should -Not -Match '(?i)\b(get|create|apply|patch|update|delete)\s+pods?\b'
        $source | Should -Not -Match '(?i)\b(exec|attach|port-forward)\b'
        $source | Should -Not -Match 'Write-(Host|Output).*?(TOKEN|PASSWORD|SECRET|KUBECONFIG)'
        $source | Should -Match 'get endpoints api'
        $source | Should -Match 'https://edu\.getkr\.com/'
    }
}
