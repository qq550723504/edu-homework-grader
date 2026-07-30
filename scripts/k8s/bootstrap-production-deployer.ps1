[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Namespace = 'edu-homework-grader',
    [switch]$ConfirmProductionCredential,
    [switch]$UpgradeDeployerRbac,
    [switch]$UpgradeKeycloakStudentProvisioner,
    [ValidateRange(1, 8760)]
    [int]$MinimumTokenLifetimeHours = 720
)

$ErrorActionPreference = 'Stop'

if (-not $ConfirmProductionCredential -and -not $UpgradeDeployerRbac -and -not $UpgradeKeycloakStudentProvisioner) {
    throw 'Pass -ConfirmProductionCredential to create the GitHub production deploy credential.'
}

if ($Namespace -ne 'edu-homework-grader') {
    throw 'The production deploy identity is restricted to the edu-homework-grader namespace.'
}

$operation = if ($UpgradeKeycloakStudentProvisioner) {
    'upgrade Keycloak student provisioner'
}
elseif ($UpgradeDeployerRbac) {
    'upgrade github-production-deployer RBAC'
}
else {
    'replace KUBECONFIG_B64'
}
if (-not $PSCmdlet.ShouldProcess('qq550723504/edu-homework-grader production environment', $operation)) {
    return
}

$rbacManifest = Join-Path $PSScriptRoot '..\..\infra\k8s\production\github-production-deployer-rbac.yaml'

& kubectl apply --server-side --filename $rbacManifest
if ($LASTEXITCODE -ne 0) {
    throw 'Kubernetes could not apply the production deploy identity RBAC.'
}

if ($UpgradeDeployerRbac) {
    Write-Information "Upgraded deploy identity RBAC in namespace $Namespace."
    return
}

if ($UpgradeKeycloakStudentProvisioner) {
    $studentProvisionerManifest = Join-Path $PSScriptRoot '..\..\infra\k8s\production\keycloak-student-provisioner-sync.yaml'
    & kubectl delete job keycloak-student-provisioner-sync-v4 --ignore-not-found --namespace $Namespace
    if ($LASTEXITCODE -ne 0) {
        throw 'Kubernetes could not remove the previous Keycloak student provisioner reconciliation Job.'
    }
    & kubectl apply --server-side --namespace $Namespace --filename $studentProvisionerManifest
    if ($LASTEXITCODE -ne 0) {
        throw 'Kubernetes could not apply the Keycloak student provisioner reconciliation resources.'
    }
    & kubectl wait --for=condition=complete job/keycloak-student-provisioner-sync-v4 --timeout=300s --namespace $Namespace
    if ($LASTEXITCODE -ne 0) {
        throw 'Keycloak student provisioner reconciliation Job did not complete.'
    }
    Write-Information "Upgraded Keycloak student provisioner in namespace $Namespace."
    return
}

$token = & kubectl create token github-production-deployer --namespace $Namespace --duration=8760h
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($token)) {
    throw 'Kubernetes could not create the production deploy identity token.'
}

function Get-CurrentClusterValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$JsonPath,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    $value = & kubectl config view --raw --minify --output "jsonpath=$JsonPath"
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($value)) {
        throw "The active Kubernetes context does not contain $Description."
    }

    return $value
}

function Assert-TokenLifetime {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Token,
        [Parameter(Mandatory = $true)]
        [int]$MinimumLifetimeHours
    )

    $segments = $Token.Split('.')
    if ($segments.Count -ne 3) {
        throw 'TokenRequest did not return a valid JWT.'
    }

    $payloadSegment = $segments[1].Replace('-', '+').Replace('_', '/')
    $padding = (4 - ($payloadSegment.Length % 4)) % 4
    $payloadJson = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payloadSegment.PadRight($payloadSegment.Length + $padding, '=')))
    try {
        $payload = $payloadJson | ConvertFrom-Json -ErrorAction Stop
        $expiration = [DateTimeOffset]::FromUnixTimeSeconds([int64]$payload.exp)
    } catch {
        throw 'TokenRequest did not return a JWT with a valid expiration.'
    }

    if ($expiration -lt [DateTimeOffset]::UtcNow.AddHours($MinimumLifetimeHours)) {
        throw 'TokenRequest lifetime is shorter than the required minimum.'
    }
}

$clusterName = Get-CurrentClusterValue -JsonPath '{.contexts[0].context.cluster}' -Description 'a cluster name'
$clusterServer = Get-CurrentClusterValue -JsonPath '{.clusters[0].cluster.server}' -Description 'a usable cluster endpoint'
$certificateAuthorityData = & kubectl config view --raw --minify --output 'jsonpath={.clusters[0].cluster.certificate-authority-data}'
if ($LASTEXITCODE -ne 0) {
    throw 'Kubernetes could not read the active cluster TLS configuration.'
}

$deployCluster = @{ server = $clusterServer }
if ($certificateAuthorityData) {
    $deployCluster['certificate-authority-data'] = $certificateAuthorityData
} else {
    throw 'The active Kubernetes context must contain certificate authority data.'
}

$deployerName = 'github-production-deployer'
$deployKubeconfig = @{
    apiVersion = 'v1'
    kind = 'Config'
    clusters = @(@{
            name = $clusterName
            cluster = $deployCluster
        })
    contexts = @(@{
            name = $deployerName
            context = @{
                cluster = $clusterName
                namespace = $Namespace
                user = $deployerName
            }
        })
    'current-context' = $deployerName
    users = @(@{
            name = $deployerName
            user = @{ token = $token }
        })
} | ConvertTo-Json -Depth 10 -Compress

Assert-TokenLifetime -Token $token -MinimumLifetimeHours $MinimumTokenLifetimeHours

[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($deployKubeconfig)) |
    & gh secret set KUBECONFIG_B64 --env production --repo qq550723504/edu-homework-grader
if ($LASTEXITCODE -ne 0) {
    throw 'GitHub could not update the production deploy credential.'
}

Write-Information "Created deploy identity $deployerName in namespace $Namespace."
