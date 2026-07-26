[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Namespace = 'edu-homework-grader',
    [Parameter(Mandatory = $true)]
    [string]$Repository,
    [switch]$ConfirmProductionCredential
)

$ErrorActionPreference = 'Stop'

if (-not $ConfirmProductionCredential) {
    throw 'Pass -ConfirmProductionCredential to create the GitHub production deploy credential.'
}

if ($Namespace -ne 'edu-homework-grader') {
    throw 'The production deploy identity is restricted to the edu-homework-grader namespace.'
}

if (-not $PSCmdlet.ShouldProcess("$Repository production environment", 'replace KUBECONFIG_B64')) {
    return
}

$rbacManifest = Join-Path $PSScriptRoot '..\..\infra\k8s\production\github-production-deployer-rbac.yaml'

& kubectl apply --server-side --filename $rbacManifest
if ($LASTEXITCODE -ne 0) {
    throw 'Kubernetes could not apply the production deploy identity RBAC.'
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

$clusterName = Get-CurrentClusterValue -JsonPath '{.contexts[0].context.cluster}' -Description 'a cluster name'
$clusterServer = Get-CurrentClusterValue -JsonPath '{.clusters[0].cluster.server}' -Description 'a usable cluster endpoint'
$certificateAuthorityData = & kubectl config view --raw --minify --output 'jsonpath={.clusters[0].cluster.certificate-authority-data}'
$insecureSkipTlsVerify = & kubectl config view --raw --minify --output 'jsonpath={.clusters[0].cluster.insecure-skip-tls-verify}'
if ($LASTEXITCODE -ne 0) {
    throw 'Kubernetes could not read the active cluster TLS configuration.'
}

$deployCluster = @{ server = $clusterServer }
if ($certificateAuthorityData) {
    $deployCluster['certificate-authority-data'] = $certificateAuthorityData
} elseif ($insecureSkipTlsVerify -eq 'true') {
    $deployCluster['insecure-skip-tls-verify'] = $true
} else {
    throw 'The active Kubernetes context does not contain certificate data.'
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

[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($deployKubeconfig)) |
    & gh secret set KUBECONFIG_B64 --env production --repo $Repository
if ($LASTEXITCODE -ne 0) {
    throw 'GitHub could not update the production deploy credential.'
}

Write-Information "Created deploy identity $deployerName in namespace $Namespace."
