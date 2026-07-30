Describe 'bootstrap-production-deployer' {
    BeforeAll {
        $scriptPath = Join-Path $PSScriptRoot 'bootstrap-production-deployer.ps1'
        $rbacPath = Join-Path $PSScriptRoot '..\..\infra\k8s\production\github-production-deployer-rbac.yaml'

        function New-TestJwt {
            param([Parameter(Mandatory = $true)][DateTimeOffset]$ExpiresAt)

            $header = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('{"alg":"none"}')).TrimEnd('=').Replace('+', '-').Replace('/', '_')
            $payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((@{ exp = $ExpiresAt.ToUnixTimeSeconds() } | ConvertTo-Json -Compress))).TrimEnd('=').Replace('+', '-').Replace('/', '_')
            return "$header.$payload.signature"
        }

        function New-FakeCommandEnvironment {
            param([Parameter(Mandatory = $true)][string]$Token)

            $fakeBin = Join-Path $TestDrive 'fake-bin'
            New-Item -ItemType Directory -Path $fakeBin -Force | Out-Null
            $logPath = Join-Path $TestDrive 'commands.log'
            $inputPath = Join-Path $TestDrive 'gh-input.txt'
            Set-Content -LiteralPath $logPath -Value $null
            Set-Content -LiteralPath (Join-Path $fakeBin 'kubectl.cmd') -NoNewline -Value @'
@echo off
echo kubectl %*>>"%FAKE_COMMAND_LOG%"
set "arguments=%*"
echo %arguments% | findstr /c:"context.cluster" >nul
if not errorlevel 1 (
  echo production-cluster
  exit /b 0
)
echo %arguments% | findstr /c:"cluster.server" >nul
if not errorlevel 1 (
  echo https://kubernetes.example.test
  exit /b 0
)
echo %arguments% | findstr /c:"certificate-authority-data" >nul
if not errorlevel 1 (
  echo Y2EtZGF0YQ==
  exit /b 0
)
echo %arguments% | findstr /c:"create token github-production-deployer" >nul
if not errorlevel 1 (
  echo %FAKE_JWT%
  exit /b 0
)
exit /b 0
'@
            Set-Content -LiteralPath (Join-Path $fakeBin 'gh.cmd') -NoNewline -Value @'
@echo off
echo gh %*>>"%FAKE_COMMAND_LOG%"
more > "%FAKE_GH_INPUT%"
exit /b 0
'@

            $previousPath = $env:Path
            $env:Path = "$fakeBin;$previousPath"
            $env:FAKE_COMMAND_LOG = $logPath
            $env:FAKE_GH_INPUT = $inputPath
            $env:FAKE_JWT = $Token
            return [pscustomobject]@{
                PreviousPath = $previousPath
                LogPath = $logPath
                InputPath = $inputPath
            }
        }

        function Restore-FakeCommandEnvironment {
            param([Parameter(Mandatory = $true)]$Environment)

            $env:Path = $Environment.PreviousPath
            Remove-Item Env:FAKE_COMMAND_LOG -ErrorAction SilentlyContinue
            Remove-Item Env:FAKE_GH_INPUT -ErrorAction SilentlyContinue
            Remove-Item Env:FAKE_JWT -ErrorAction SilentlyContinue
        }

        function Get-RbacDocuments {
            return @(
                (Get-Content -Raw -LiteralPath $rbacPath) -split '(?m)^---\s*\r?\n'
            )
        }
    }

    It 'requires confirmation before creating a deploy credential' {
        { & $scriptPath -WhatIf } |
            Should -Throw -ExpectedMessage '*-ConfirmProductionCredential*'
    }

    It 'upgrades deployer RBAC without creating or uploading a credential' {
        $environment = New-FakeCommandEnvironment -Token (New-TestJwt -ExpiresAt ([DateTimeOffset]::UtcNow.AddHours(800)))
        try {
            { & $scriptPath -UpgradeDeployerRbac -InformationAction SilentlyContinue } | Should -Not -Throw

            $commandLog = Get-Content -Raw $environment.LogPath
            $commandLog | Should -Match '(?m)^kubectl apply --server-side --filename '
            $commandLog | Should -Not -Match '(?m)^create token '
            $commandLog | Should -Not -Match '(?m)^gh secret set '
        } finally {
            Restore-FakeCommandEnvironment -Environment $environment
        }
    }

    It 'rejects an arbitrary repository before invoking Kubernetes or GitHub' {
        Mock kubectl { throw 'kubectl must not run' }
        Mock gh { throw 'gh must not run' }

        { & $scriptPath -Repository 'attacker/repository' -ConfirmProductionCredential } |
            Should -Throw -ExpectedMessage '*Repository*'

        Assert-MockCalled kubectl -Times 0 -Exactly
        Assert-MockCalled gh -Times 0 -Exactly
    }

    It 'rejects a short-lived token before uploading the GitHub Environment credential' {
        $environment = New-FakeCommandEnvironment -Token (New-TestJwt -ExpiresAt ([DateTimeOffset]::UtcNow.AddHours(1)))
        try {
            { & $scriptPath -ConfirmProductionCredential -InformationAction SilentlyContinue } |
                Should -Throw -ExpectedMessage '*TokenRequest lifetime is shorter than the required minimum*'

            (Get-Content -Raw $environment.LogPath) | Should -Not -Match '(?m)^gh secret set'
        } finally {
            Restore-FakeCommandEnvironment -Environment $environment
        }
    }

    It 'uploads only a sufficient-lifetime credential to the fixed production Environment' {
        $token = New-TestJwt -ExpiresAt ([DateTimeOffset]::UtcNow.AddHours(800))
        $environment = New-FakeCommandEnvironment -Token $token
        try {
            { & $scriptPath -ConfirmProductionCredential -InformationAction SilentlyContinue } | Should -Not -Throw

            (Get-Content -Raw $environment.LogPath) |
                Should -Match '(?m)^gh secret set KUBECONFIG_B64 --env production --repo qq550723504/edu-homework-grader\r?$'
            $kubeconfig = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((Get-Content -Raw $environment.InputPath))) | ConvertFrom-Json
            @($kubeconfig.users).Count | Should -Be 1
            $kubeconfig.users[0].name | Should -Be 'github-production-deployer'
            $kubeconfig.users[0].user.token | Should -Be $token
        } finally {
            Restore-FakeCommandEnvironment -Environment $environment
        }
    }

    It 'does not print credentials' {
        $source = Get-Content -Raw $scriptPath
        $source | Should -Not -Match 'Write-(Host|Output).*?(TOKEN|KUBECONFIG|SECRET)'
        $source | Should -Match 'gh secret set KUBECONFIG_B64 --env production'
        $source | Should -Match '--repo qq550723504/edu-homework-grader'
        $source | Should -Not -Match '\$Repository'
        $source | Should -Match 'kubectl create token'
    }

    It 'grants only the exact namespace-scoped deployment rules' {
        $documents = Get-RbacDocuments
        @($documents | Where-Object { $_ -match '(?m)^kind:\s*ClusterRole\s*$' }).Count |
            Should -Be 0
        $roleDocuments = @(
            $documents | Where-Object { $_ -match '(?m)^kind:\s*Role\s*$' }
        )
        $roleDocuments | Should -HaveCount 1
        $role = $roleDocuments[0]
        $role | Should -Match '(?ms)^metadata:\s*\r?\n.*?^\s{2}name:\s*github-production-deployer\s*$'
        $role | Should -Match '(?ms)^metadata:\s*\r?\n.*?^\s{2}namespace:\s*edu-homework-grader\s*$'

        $actualRules = [regex]::Match(
            $role,
            '(?ms)^rules:\s*\r?\n(?<rules>.*)$'
        ).Groups['rules'].Value.Trim() -replace "`r`n", "`n"
        $expectedRules = @'
  - apiGroups: ["apps"]
    resources: ["deployments"]
    resourceNames: ["api", "grader", "web", "languagetool"]
    verbs: ["get", "patch"]
  - apiGroups: ["batch"]
    resources: ["cronjobs"]
    resourceNames: ["student-activation-expiry", "operational-evaluation-retention", "production-alert"]
    verbs: ["get", "create", "patch", "delete"]
  - apiGroups: [""]
    resources: ["configmaps"]
    resourceNames: ["keycloak-student-provisioner-sync-v4"]
    verbs: ["get", "create", "patch"]
  - apiGroups: ["batch"]
    resources: ["jobs"]
    resourceNames: ["keycloak-student-provisioner-sync-v4"]
    verbs: ["get", "create", "patch"]
  - apiGroups: [""]
    resources: ["endpoints"]
    resourceNames: ["api"]
    verbs: ["get"]
'@.Trim() -replace "`r`n", "`n"

        $actualRules | Should -BeExactly $expectedRules
        $actualRules | Should -Not -Match '(?i)\bsecrets?\b'
        $actualRules | Should -Not -Match '(?i)\bpods?(?:/|\b)'
        $actualRules | Should -Not -Match '\*'
    }
}
