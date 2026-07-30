Describe 'deploy-production' {
BeforeAll {
    $script:scriptPath = Join-Path $PSScriptRoot 'deploy-production.ps1'
    $script:validSha = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    $global:DeployProductionRealKubectl = (
        Get-Command kubectl.exe -CommandType Application |
            Select-Object -First 1
    ).Source
    $originalKubeconfig = $env:KUBECONFIG
    $env:KUBECONFIG = Join-Path $TestDrive 'fake-kubeconfig'
    Set-Content -LiteralPath $env:KUBECONFIG -Value @'
apiVersion: v1
kind: Config
clusters: []
contexts: []
current-context: ""
users: []
'@

    function Get-ManifestResources {
        param([Parameter(Mandatory = $true)][string]$Content)

        $resources = [System.Collections.Generic.List[object]]::new()
        foreach ($document in @($Content -split '(?m)^---\s*\r?\n')) {
            $kindMatch = [regex]::Match($document, '(?m)^kind:\s*(\S+)\s*$')
            $metadataMatch = [regex]::Match(
                $document,
                '(?ms)^metadata:\s*\r?\n(?<body>.*?)(?=^\S|\z)'
            )
            if (-not $kindMatch.Success -or -not $metadataMatch.Success) {
                continue
            }
            $nameMatch = [regex]::Match(
                $metadataMatch.Groups['body'].Value,
                '(?m)^\s{2}name:\s*(\S+)\s*$'
            )
            if (-not $nameMatch.Success) {
                continue
            }
            $resources.Add([pscustomobject]@{
                Kind = $kindMatch.Groups[1].Value
                Name = $nameMatch.Groups[1].Value
                Content = $document
            })
        }
        return @($resources)
    }

    function Get-WorkloadImages {
        param([Parameter(Mandatory = $true)][object[]]$Resources)

        $images = [System.Collections.Generic.List[string]]::new()
        foreach ($resource in $Resources) {
            if ($resource.Kind -eq 'Job') {
                continue
            }
            foreach ($match in [regex]::Matches(
                $resource.Content,
                '(?m)^\s+(?:-\s+)?image:\s*(\S+)\s*$'
            )) {
                $images.Add($match.Groups[1].Value)
            }
        }
        return @($images)
    }

    function Assert-ManagedReleaseObjects {
        param(
            [Parameter(Mandatory = $true)][object[]]$Resources,
            [Parameter(Mandatory = $true)][bool]$IncludesProductionAlert
        )

        $expected = @(
            'Deployment/api'
            'Deployment/grader'
            'Deployment/languagetool'
            'Deployment/web'
            'CronJob/student-activation-expiry'
            'CronJob/operational-evaluation-retention'
            'ConfigMap/keycloak-student-provisioner-sync-v4'
            'Job/keycloak-student-provisioner-sync-v4'
        )
        if ($IncludesProductionAlert) {
            $expected += 'CronJob/production-alert'
        }
        $actual = @($Resources | ForEach-Object { "$($_.Kind)/$($_.Name)" })

        $actual | Should -HaveCount $expected.Count
        foreach ($key in $expected) {
            $actual | Should -Contain $key
        }
        foreach ($forbiddenPattern in @(
            'Deployment/(keycloak|redis)'
            'StatefulSet/'
            'Service/'
            'Ingress/'
            'Namespace/'
            'postgres'
            '^(ServiceAccount|Role|RoleBinding|NetworkPolicy)/operational-evaluation-'
        )) {
            $actual | Should -Not -Match $forbiddenPattern
        }
    }

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

        if ($joined -eq 'get cronjob student-activation-expiry operational-evaluation-retention --output json --namespace edu-homework-grader') {
            return @'
{"items":[
  {"metadata":{"name":"student-activation-expiry"},"spec":{"jobTemplate":{"spec":{"template":{"spec":{"containers":[{"name":"expire","image":"registry.example/api-cron@sha256:old-cron"}]}}}}}},
  {"metadata":{"name":"operational-evaluation-retention"},"spec":{"jobTemplate":{"spec":{"template":{"spec":{"containers":[{"name":"expire","image":"registry.example/api-eval-cron@sha256:old-eval-cron"}]}}}}}}
]}
'@
        }

        if ($joined -eq 'get cronjob production-alert --ignore-not-found --output json --namespace edu-homework-grader') {
            return @()
        }

        if ($joined -eq 'get job keycloak-student-provisioner-sync-v4 --output json --namespace edu-homework-grader') {
            if ($global:DeployProductionTestState.KeycloakProfileJobFailed) {
                return '{"status":{"conditions":[{"type":"Failed","status":"True"}]}}'
            }
            return '{"status":{"conditions":[{"type":"Complete","status":"True"}]}}'
        }

        if ($joined -match '^get deployment (api|grader|web|languagetool) --output json --namespace edu-homework-grader$') {
            $name = [string]$Arguments[2]
            $isTarget = $global:DeployProductionTestState.ApplyCount -eq 1
            $isRollback = $global:DeployProductionTestState.ApplyCount -ge 2
            $deploymentReadKey = "$($global:DeployProductionTestState.ApplyCount)/$name"
            if (-not $global:DeployProductionTestState.DeploymentReadCounts.ContainsKey($deploymentReadKey)) {
                $global:DeployProductionTestState.DeploymentReadCounts[$deploymentReadKey] = 0
            }
            $global:DeployProductionTestState.DeploymentReadCounts[$deploymentReadKey]++
            if (
                ($isTarget -and $global:DeployProductionTestState.TargetDeploymentNeverReady) -or
                ($isRollback -and $global:DeployProductionTestState.RollbackDeploymentNeverReady)
            ) {
                return ('{"metadata":{"name":"' + $name + '","generation":7},"spec":{"replicas":1},"status":{"observedGeneration":6,"updatedReplicas":0,"availableReplicas":0}}')
            }
            if (
                $isTarget -and
                $global:DeployProductionTestState.TargetDeploymentStatusMissingOnFirstRead -and
                $name -eq 'api' -and
                $global:DeployProductionTestState.DeploymentReadCounts[$deploymentReadKey] -eq 1
            ) {
                return ('{"metadata":{"name":"' + $name + '","generation":7},"spec":{"replicas":1},"status":{}}')
            }
            return ('{"metadata":{"name":"' + $name + '","generation":7},"spec":{"replicas":1},"status":{"observedGeneration":7,"updatedReplicas":1,"availableReplicas":1}}')
        }

        if ($joined -match '^apply --server-side(?: --field-manager github-production-deployer)?(?: --force-conflicts)? --filename ') {
            $global:DeployProductionTestState.ApplyCount++
            $manifestPath = [string]$Arguments[-1]
            $global:DeployProductionTestState.AppliedManifests.Add(
                (Get-Content -Raw -LiteralPath $manifestPath)
            )
            return 'applied'
        }

        if ($joined -eq 'delete cronjob production-alert --ignore-not-found --namespace edu-homework-grader') {
            return 'deleted'
        }

        if ($joined -match '^rollout status deployment/') {
            throw 'forbidden: User system:serviceaccount:edu-homework-grader:github-production-deployer cannot list resource "deployments"'
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
            $output = & $global:DeployProductionRealKubectl kustomize .
            if ($LASTEXITCODE -ne 0) {
                throw 'The real test-only Kustomize render failed.'
            }
            return $output
        }
        if ($joined -match '^edit set image ') {
            $replacement = [string]$Arguments[-1]
            $separator = $replacement.IndexOf('=')
            $sourceImage = $replacement.Substring(0, $separator)
            $targetImage = $replacement.Substring($separator + 1)
            $tagSeparator = $targetImage.LastIndexOf(':')
            $newName = $targetImage.Substring(0, $tagSeparator)
            $newTag = $targetImage.Substring($tagSeparator + 1)
            $kustomizationPath = Join-Path (Get-Location).Path 'kustomization.yaml'
            $kustomization = Get-Content -Raw -LiteralPath $kustomizationPath
            if ($kustomization -notmatch '(?m)^images:\s*$') {
                Add-Content -LiteralPath $kustomizationPath -Value 'images:'
            }
            Add-Content -LiteralPath $kustomizationPath -Value @"
  - name: $sourceImage
    newName: $newName
    newTag: $newTag
"@
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
    Remove-Variable DeployProductionRealKubectl -Scope Global -ErrorAction SilentlyContinue
}

BeforeEach {
    $global:DeployProductionTestState = @{
        KubectlCalls             = [System.Collections.Generic.List[string]]::new()
        KustomizeCalls           = [System.Collections.Generic.List[string]]::new()
        KustomizeDirectories     = [System.Collections.Generic.List[string]]::new()
        AppliedManifests         = [System.Collections.Generic.List[string]]::new()
        PublicHealthCalls        = [System.Collections.Generic.List[string]]::new()
        ApplyCount               = 0
        DeploymentReadCounts     = @{}
        TargetDeploymentNeverReady = $false
        RollbackDeploymentNeverReady = $false
        TargetDeploymentStatusMissingOnFirstRead = $false
        KeycloakProfileJobFailed = $false
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
        @($global:DeployProductionTestState.KubectlCalls -match '^get deployment (api|grader|web|languagetool) --output json --namespace edu-homework-grader$').Count |
            Should -Be 4
        $global:DeployProductionTestState.KubectlCalls |
            Should -Not -Match '^rollout status deployment/'

        $resources = @(
            Get-ManifestResources `
                -Content $global:DeployProductionTestState.AppliedManifests[0]
        )
        Assert-ManagedReleaseObjects -Resources $resources -IncludesProductionAlert $true
        $images = @(Get-WorkloadImages -Resources $resources)
        $images | Should -HaveCount 8
        foreach ($image in $images) {
            $image | Should -Match ([regex]::Escape(":$validSha") + '$')
            $image | Should -Not -Match 'sha-not-published'
        }
    }

    It 'deploys the release-evidence image digests rather than mutable SHA tags' {
        $digests = @{
            api = 'sha256:' + ('a' * 64)
            grader = 'sha256:' + ('b' * 64)
            web = 'sha256:' + ('c' * 64)
            languagetool = 'sha256:' + ('d' * 64)
        } | ConvertTo-Json -Compress

        & $scriptPath `
            -ImageSha $validSha `
            -ImageDigestsJson $digests `
            -SkipPublicHealthCheck

        $global:DeployProductionTestState.KustomizeCalls |
            Should -Not -Match '^edit set image '
        $images = @(
            Get-WorkloadImages -Resources @(
                Get-ManifestResources `
                    -Content $global:DeployProductionTestState.AppliedManifests[0]
            )
        )
        $apiImage = 'ghcr.io/qq550723504/edu-homework-grader-api@sha256:' + ('a' * 64)
        $graderImage = 'ghcr.io/qq550723504/edu-homework-grader-grader@sha256:' + ('b' * 64)
        $webImage = 'ghcr.io/qq550723504/edu-homework-grader-web@sha256:' + ('c' * 64)
        $languageToolImage = 'ghcr.io/qq550723504/edu-homework-grader-languagetool@sha256:' + ('d' * 64)
        $images | Should -Contain $apiImage
        $images | Should -Contain $graderImage
        $images | Should -Contain $webImage
        $images | Should -Contain $languageToolImage
    }

    It 'keeps shared ownership labels out of immutable deployment selectors' {
        & $scriptPath -ImageSha $validSha -SkipPublicHealthCheck

        @(
            $global:DeployProductionTestState.KubectlCalls -match
                '^apply --server-side --field-manager github-production-deployer --force-conflicts --filename '
        ).Count | Should -Be 1

        $resources = @(
            Get-ManifestResources `
                -Content $global:DeployProductionTestState.AppliedManifests[0]
        )
        foreach ($deployment in @($resources | Where-Object { $_.Kind -eq 'Deployment' })) {
            $selector = [regex]::Match(
                $deployment.Content,
                '(?ms)^  selector:\s*\r?\n(?<body>.*?)(?=^  template:)'
            ).Groups['body'].Value

            $selector | Should -Match (
                'app\.kubernetes\.io/name:\s*' + [regex]::Escape($deployment.Name)
            )
            $selector | Should -Not -Match 'app\.kubernetes\.io/part-of:'
        }
    }

    It 'includes the Keycloak profile reconciliation resources in every release' {
        & $scriptPath -ImageSha $validSha -SkipPublicHealthCheck

        $resources = @(
            Get-ManifestResources `
                -Content $global:DeployProductionTestState.AppliedManifests[0]
        )

        $resources | ForEach-Object { "$($_.Kind)/$($_.Name)" } |
            Should -Contain 'ConfigMap/keycloak-student-provisioner-sync-v4'
        $resources | ForEach-Object { "$($_.Kind)/$($_.Name)" } |
            Should -Contain 'Job/keycloak-student-provisioner-sync-v4'
    }

    It 'does not give the release path ownership of Keycloak Job retries' {
        & $scriptPath -ImageSha $validSha -SkipPublicHealthCheck

        $global:DeployProductionTestState.KubectlCalls |
            Should -Not -Match '^delete job keycloak-student-provisioner-sync-v4 '
    }

    It 'fails the release when the Keycloak profile reconciliation Job fails' {
        $global:DeployProductionTestState.KeycloakProfileJobFailed = $true

        { & $scriptPath -ImageSha $validSha -SkipPublicHealthCheck } |
            Should -Throw '*Production release * failed; rollback succeeded.*'
        $global:DeployProductionTestState.KubectlCalls |
            Should -Contain 'get job keycloak-student-provisioner-sync-v4 --output json --namespace edu-homework-grader'
    }

    It 'treats omitted deployment status fields as not ready until the named deployment becomes ready' {
        $global:DeployProductionTestState.TargetDeploymentStatusMissingOnFirstRead = $true

        & $scriptPath -ImageSha $validSha -SkipPublicHealthCheck -RolloutTimeoutSeconds 6

        $global:DeployProductionTestState.ApplyCount | Should -Be 1
        @($global:DeployProductionTestState.KubectlCalls -match '^get deployment api --output json --namespace edu-homework-grader$').Count |
            Should -Be 2
        $global:DeployProductionTestState.KubectlCalls |
            Should -Not -Match '^rollout status deployment/'
    }

    It 'restores the exact captured images after rollout failure' {
        $global:DeployProductionTestState.TargetDeploymentNeverReady = $true

        { & $scriptPath -ImageSha $validSha -SkipPublicHealthCheck -RolloutTimeoutSeconds 1 } |
            Should -Throw '*rollback succeeded*'

        $global:DeployProductionTestState.ApplyCount | Should -Be 2
        $rollbackResources = @(
            Get-ManifestResources `
                -Content $global:DeployProductionTestState.AppliedManifests[1]
        )
        Assert-ManagedReleaseObjects -Resources $rollbackResources -IncludesProductionAlert $false
        $rollbackImages = @(Get-WorkloadImages -Resources $rollbackResources)
        $rollbackImages | Should -HaveCount 7
        foreach ($expectedImage in @(
            'registry.example/migrate@sha256:old-migrate'
            'registry.example/api@sha256:old-api'
            'registry.example/grader@sha256:old-grader'
            'registry.example/web@sha256:old-web'
            'registry.example/languagetool@sha256:old-language'
            'registry.example/api-cron@sha256:old-cron'
            'registry.example/api-eval-cron@sha256:old-eval-cron'
        )) {
            $rollbackImages | Should -Contain $expectedImage
        }
        $global:DeployProductionTestState.AppliedManifests[1] |
            Should -Not -Match 'sha-not-published'
        $global:DeployProductionTestState.KubectlCalls |
            Should -Contain 'delete cronjob production-alert --ignore-not-found --namespace edu-homework-grader'
    }

    It 'rolls back when the API Service has no ready endpoints' {
        $global:DeployProductionTestState.EndpointReady = $false

        { & $scriptPath -ImageSha $validSha -SkipPublicHealthCheck -EndpointTimeoutSeconds 0 } |
            Should -Throw '*rollback succeeded*'

        $global:DeployProductionTestState.ApplyCount | Should -Be 2
    }

    It 'reports a rollback failure separately from the release failure' {
        $global:DeployProductionTestState.TargetDeploymentNeverReady = $true
        $global:DeployProductionTestState.RollbackDeploymentNeverReady = $true

        { & $scriptPath -ImageSha $validSha -SkipPublicHealthCheck -RolloutTimeoutSeconds 1 } |
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
