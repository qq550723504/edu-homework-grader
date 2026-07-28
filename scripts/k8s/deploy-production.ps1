[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ImageSha,

    [string]$ImageDigestsJson,

    [switch]$SkipPublicHealthCheck,

    [ValidateRange(0, 3600)]
    [int]$EndpointTimeoutSeconds = 120,

    [ValidateRange(1, 3600)]
    [int]$RolloutTimeoutSeconds = 300
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Namespace = 'edu-homework-grader'
$ProductionManifestPath = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot '..\..\infra\k8s\production')
)
$PublicHealthUri = 'https://edu.getkr.com/'
$ManagedRepositories = [ordered]@{
    Api          = 'ghcr.io/qq550723504/edu-homework-grader-api'
    Grader       = 'ghcr.io/qq550723504/edu-homework-grader-grader'
    Web          = 'ghcr.io/qq550723504/edu-homework-grader-web'
    LanguageTool = 'ghcr.io/qq550723504/edu-homework-grader-languagetool'
}
$ManagedDeployments = @('api', 'grader', 'web', 'languagetool')

function Assert-ImageSha {
    param([string]$Value)

    if ($Value -notmatch '^[0-9a-f]{40}$') {
        throw 'ImageSha must be a 40-character lower-case Git SHA.'
    }
}

function ConvertTo-ReleaseImagesFromDigests {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DigestsJson
    )

    try {
        $digests = $DigestsJson | ConvertFrom-Json -AsHashtable
    }
    catch {
        throw 'ImageDigestsJson must be a JSON object.'
    }

    $expectedKeys = @('api', 'grader', 'web', 'languagetool')
    if ($null -eq $digests -or $digests.Count -ne $expectedKeys.Count) {
        throw 'ImageDigestsJson must contain exactly api, grader, web and languagetool.'
    }
    foreach ($key in $expectedKeys) {
        if (-not $digests.ContainsKey($key)) {
            throw 'ImageDigestsJson must contain exactly api, grader, web and languagetool.'
        }
        if ([string]$digests[$key] -notmatch '^sha256:[0-9a-f]{64}$') {
            throw "Image digest for $key is not a SHA-256 digest."
        }
    }

    return [ordered]@{
        ApiInit        = "$($ManagedRepositories.Api)@$($digests.api)"
        Api            = "$($ManagedRepositories.Api)@$($digests.api)"
        Grader         = "$($ManagedRepositories.Grader)@$($digests.grader)"
        Web            = "$($ManagedRepositories.Web)@$($digests.web)"
        LanguageTool   = "$($ManagedRepositories.LanguageTool)@$($digests.languagetool)"
        ExpiryCronJob  = "$($ManagedRepositories.Api)@$($digests.api)"
    }
}

function Assert-Kubeconfig {
    if ([string]::IsNullOrWhiteSpace($env:KUBECONFIG)) {
        throw 'A deployment kubeconfig path is required.'
    }
    if (-not (Test-Path -LiteralPath $env:KUBECONFIG -PathType Leaf)) {
        throw 'The deployment kubeconfig path does not exist.'
    }
}

function Invoke-NativeTool {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Tool,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $global:LASTEXITCODE = 0
    $output = & $Tool @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Tool command failed with exit code $exitCode."
    }
    return $output
}

function ConvertFrom-ToolJson {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Output,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    $json = $Output -join [Environment]::NewLine
    if ([string]::IsNullOrWhiteSpace($json)) {
        throw "$Description returned no data."
    }
    try {
        return $json | ConvertFrom-Json
    }
    catch {
        throw "$Description returned invalid JSON."
    }
}

function Get-NamedWorkloadImage {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Workloads,

        [Parameter(Mandatory = $true)]
        [string]$WorkloadName,

        [Parameter(Mandatory = $true)]
        [string]$ContainerName,

        [switch]$InitContainer,

        [switch]$CronJob
    )

    $workload = @($Workloads | Where-Object { $_.metadata.name -eq $WorkloadName })
    if ($workload.Count -ne 1) {
        throw "Expected one $WorkloadName workload while capturing managed images."
    }

    if ($CronJob) {
        $containers = @($workload[0].spec.jobTemplate.spec.template.spec.containers)
    }
    elseif ($InitContainer) {
        $containers = @($workload[0].spec.template.spec.initContainers)
    }
    else {
        $containers = @($workload[0].spec.template.spec.containers)
    }
    $container = @($containers | Where-Object { $_.name -eq $ContainerName })
    if ($container.Count -ne 1 -or [string]::IsNullOrWhiteSpace($container[0].image)) {
        throw "Expected one $ContainerName container while capturing managed images."
    }

    return [string]$container[0].image
}

function Assert-CapturedImage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Image,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if ($Image -notmatch '^[A-Za-z0-9][A-Za-z0-9._/@:+-]{0,1023}$') {
        throw "Captured image for $Name is not a safe OCI image reference."
    }
}

function Get-ManagedImages {
    $deploymentOutput = @(
        Invoke-NativeTool -Tool 'kubectl' -Arguments @(
            'get', 'deployments', 'api', 'grader', 'web', 'languagetool',
            '--output', 'json', '--namespace', $Namespace
        )
    )
    $deploymentDocument = ConvertFrom-ToolJson `
        -Output $deploymentOutput `
        -Description 'Managed Deployment query'

    $cronJobOutput = @(
        Invoke-NativeTool -Tool 'kubectl' -Arguments @(
            'get', 'cronjob', 'student-activation-expiry',
            '--output', 'json', '--namespace', $Namespace
        )
    )
    $cronJobDocument = ConvertFrom-ToolJson `
        -Output $cronJobOutput `
        -Description 'Managed CronJob query'

    $images = [ordered]@{
        ApiInit       = Get-NamedWorkloadImage `
            -Workloads @($deploymentDocument.items) `
            -WorkloadName 'api' `
            -ContainerName 'migrate' `
            -InitContainer
        Api           = Get-NamedWorkloadImage `
            -Workloads @($deploymentDocument.items) `
            -WorkloadName 'api' `
            -ContainerName 'api'
        Grader        = Get-NamedWorkloadImage `
            -Workloads @($deploymentDocument.items) `
            -WorkloadName 'grader' `
            -ContainerName 'grader'
        Web           = Get-NamedWorkloadImage `
            -Workloads @($deploymentDocument.items) `
            -WorkloadName 'web' `
            -ContainerName 'web'
        LanguageTool  = Get-NamedWorkloadImage `
            -Workloads @($deploymentDocument.items) `
            -WorkloadName 'languagetool' `
            -ContainerName 'languagetool'
        ExpiryCronJob = Get-NamedWorkloadImage `
            -Workloads @($cronJobDocument) `
            -WorkloadName 'student-activation-expiry' `
            -ContainerName 'expire' `
            -CronJob
    }

    foreach ($entry in $images.GetEnumerator()) {
        Assert-CapturedImage -Image $entry.Value -Name $entry.Key
    }
    return $images
}

function ConvertTo-YamlString {
    param([Parameter(Mandatory = $true)][string]$Value)

    return ($Value | ConvertTo-Json -Compress)
}

function New-ExactImagePatch {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$ApiVersion,

        [Parameter(Mandatory = $true)]
        [string]$Kind,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Spec
    )

    $content = @"
apiVersion: $ApiVersion
kind: $Kind
metadata:
  name: $Name
$Spec
"@
    Set-Content -LiteralPath $Path -Value $content -NoNewline
}

function Add-ExactImagePatches {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$Images,

        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    $requiredKeys = @('ApiInit', 'Api', 'Grader', 'Web', 'LanguageTool', 'ExpiryCronJob')
    foreach ($key in $requiredKeys) {
        if (-not $Images.Contains($key)) {
            throw "Exact rollback image map is missing $key."
        }
        Assert-CapturedImage -Image ([string]$Images[$key]) -Name $key
    }

    $apiInit = ConvertTo-YamlString ([string]$Images.ApiInit)
    $api = ConvertTo-YamlString ([string]$Images.Api)
    New-ExactImagePatch `
        -Path (Join-Path $Destination 'managed-api-images.yaml') `
        -ApiVersion 'apps/v1' `
        -Kind 'Deployment' `
        -Name 'api' `
        -Spec @"
spec:
  template:
    spec:
      initContainers:
        - name: migrate
          image: $apiInit
      containers:
        - name: api
          image: $api
"@

    foreach ($deployment in @(
        @{ Name = 'grader'; Key = 'Grader' },
        @{ Name = 'web'; Key = 'Web' },
        @{ Name = 'languagetool'; Key = 'LanguageTool' }
    )) {
        $image = ConvertTo-YamlString ([string]$Images[$deployment.Key])
        New-ExactImagePatch `
            -Path (Join-Path $Destination "managed-$($deployment.Name)-image.yaml") `
            -ApiVersion 'apps/v1' `
            -Kind 'Deployment' `
            -Name $deployment.Name `
            -Spec @"
spec:
  template:
    spec:
      containers:
        - name: $($deployment.Name)
          image: $image
"@
    }

    $cronImage = ConvertTo-YamlString ([string]$Images.ExpiryCronJob)
    New-ExactImagePatch `
        -Path (Join-Path $Destination 'managed-expiry-image.yaml') `
        -ApiVersion 'batch/v1' `
        -Kind 'CronJob' `
        -Name 'student-activation-expiry' `
        -Spec @"
spec:
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: expire
              image: $cronImage
"@

    $kustomizationPath = Join-Path $Destination 'kustomization.yaml'
    $patchConfiguration = @'
  - path: managed-api-images.yaml
  - path: managed-grader-image.yaml
  - path: managed-web-image.yaml
  - path: managed-languagetool-image.yaml
  - path: managed-expiry-image.yaml
'@
    Add-Content -LiteralPath $kustomizationPath -Value $patchConfiguration
}

function Initialize-ReleaseKustomization {
    param([Parameter(Mandatory = $true)][string]$Destination)

    Set-Content `
        -LiteralPath (Join-Path $Destination 'kustomization.yaml') `
        -Value @'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: edu-homework-grader
labels:
  - includeSelectors: true
    pairs:
      app.kubernetes.io/part-of: edu-homework-grader
resources:
  - application.yaml
  - student-activation-expiry.yaml
patches:
  - path: managed-keycloak-exclusion.yaml
'@

    Set-Content `
        -LiteralPath (Join-Path $Destination 'managed-keycloak-exclusion.yaml') `
        -Value @'
$patch: delete
apiVersion: apps/v1
kind: Deployment
metadata:
  name: keycloak
'@
}

function New-RenderedRelease {
    param(
        [string]$Sha,

        [System.Collections.IDictionary]$ExactImages,

        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    $usingSha = -not [string]::IsNullOrWhiteSpace($Sha)
    $usingExactImages = $null -ne $ExactImages
    if ($usingSha -eq $usingExactImages) {
        throw 'Render exactly one of Sha or ExactImages.'
    }
    if ($usingSha) {
        Assert-ImageSha -Value $Sha
    }

    Copy-Item -LiteralPath $ProductionManifestPath -Destination $Destination -Recurse
    Initialize-ReleaseKustomization -Destination $Destination

    Push-Location $Destination
    try {
        if ($usingSha) {
            foreach ($repository in $ManagedRepositories.Values) {
                $replacement = "$repository=${repository}:$Sha"
                $null = Invoke-NativeTool `
                    -Tool 'kustomize' `
                    -Arguments @('edit', 'set', 'image', $replacement)
            }
        }
        else {
            Add-ExactImagePatches -Images $ExactImages -Destination $Destination
        }

        $renderedOutput = @(
            Invoke-NativeTool -Tool 'kustomize' -Arguments @('build', '.')
        )
    }
    finally {
        Pop-Location
    }

    if ($renderedOutput.Count -eq 0) {
        throw 'Kustomize rendered an empty production release.'
    }
    $renderedPath = Join-Path $Destination 'release.yaml'
    Set-Content `
        -LiteralPath $renderedPath `
        -Value ($renderedOutput -join [Environment]::NewLine) `
        -NoNewline
    return $renderedPath
}

function Apply-RenderedRelease {
    param([Parameter(Mandatory = $true)][string]$ManifestPath)

    $null = Invoke-NativeTool `
        -Tool 'kubectl' `
        -Arguments @(
            'apply', '--server-side',
            '--field-manager', 'github-production-deployer',
            '--force-conflicts', '--filename', $ManifestPath
        )
}

function Get-OptionalPropertyValue {
    param(
        [object]$Object,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if ($null -eq $Object) {
        return $null
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function Wait-DeploymentRollouts {
    foreach ($deployment in $ManagedDeployments) {
        $deadline = [DateTimeOffset]::UtcNow.AddSeconds($RolloutTimeoutSeconds)
        while ($true) {
            $deploymentOutput = @(
                Invoke-NativeTool -Tool 'kubectl' -Arguments @(
                    'get', 'deployment', $deployment,
                    '--output', 'json', '--namespace', $Namespace
                )
            )
            $deploymentDocument = ConvertFrom-ToolJson `
                -Output $deploymentOutput `
                -Description "Deployment $deployment query"

            $spec = Get-OptionalPropertyValue -Object $deploymentDocument -Name 'spec'
            $desiredReplicaValue = Get-OptionalPropertyValue -Object $spec -Name 'replicas'
            $desiredReplicas = if ($null -eq $desiredReplicaValue) {
                1
            }
            else {
                [int]$desiredReplicaValue
            }
            $status = Get-OptionalPropertyValue -Object $deploymentDocument -Name 'status'
            $observedGeneration = [int](Get-OptionalPropertyValue -Object $status -Name 'observedGeneration')
            $updatedReplicas = [int](Get-OptionalPropertyValue -Object $status -Name 'updatedReplicas')
            $availableReplicas = [int](Get-OptionalPropertyValue -Object $status -Name 'availableReplicas')
            if (
                $observedGeneration -ge [int]$deploymentDocument.metadata.generation -and
                $updatedReplicas -ge $desiredReplicas -and
                $availableReplicas -ge $desiredReplicas
            ) {
                break
            }

            if ([DateTimeOffset]::UtcNow -ge $deadline) {
                throw "Deployment $deployment did not become ready."
            }
            $remainingMilliseconds = [int][Math]::Max(
                1,
                [Math]::Min(5000, ($deadline - [DateTimeOffset]::UtcNow).TotalMilliseconds)
            )
            Start-Sleep -Milliseconds $remainingMilliseconds
        }
    }
}

function Wait-ApiServiceEndpoints {
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($EndpointTimeoutSeconds)
    $getApiEndpointsArguments = 'get endpoints api --output json --namespace edu-homework-grader'.Split(' ')

    while ($true) {
        $endpointOutput = @(
            Invoke-NativeTool -Tool 'kubectl' -Arguments $getApiEndpointsArguments
        )
        $endpointDocument = ConvertFrom-ToolJson `
            -Output $endpointOutput `
            -Description 'API Service endpoints query'

        $readyAddresses = @()
        if ($null -ne $endpointDocument.PSObject.Properties['subsets']) {
            foreach ($subset in @($endpointDocument.subsets)) {
                if ($null -ne $subset -and $null -ne $subset.PSObject.Properties['addresses']) {
                    $readyAddresses += @($subset.addresses)
                }
            }
        }
        if ($readyAddresses.Count -gt 0) {
            return
        }
        if ([DateTimeOffset]::UtcNow -ge $deadline) {
            throw 'API Service has no ready endpoints.'
        }
        Start-Sleep -Seconds 5
    }
}

function Wait-PublicHealth {
    $response = Invoke-WebRequest `
        -Uri $PublicHealthUri `
        -Method Get `
        -MaximumRedirection 5 `
        -TimeoutSec 30
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 400) {
        throw 'Public production health check failed.'
    }
}

function Wait-ProductionHealthy {
    Wait-DeploymentRollouts
    Wait-ApiServiceEndpoints
    if (-not $SkipPublicHealthCheck) {
        Wait-PublicHealth
    }
}

function Restore-ManagedImages {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$Images,

        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    $rollbackManifest = New-RenderedRelease `
        -ExactImages $Images `
        -Destination $Destination
    Apply-RenderedRelease -ManifestPath $rollbackManifest
    Wait-DeploymentRollouts
}

function Write-ReleaseSummary {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetSha,

        [System.Collections.IDictionary]$PreviousImages,

        [Parameter(Mandatory = $true)]
        [DateTimeOffset]$StartedAt,

        [Parameter(Mandatory = $true)]
        [string]$Result
    )

    if ([string]::IsNullOrWhiteSpace($env:GITHUB_STEP_SUMMARY)) {
        return
    }

    $lines = @(
        '## Production release'
        ''
        "- Target SHA: ``$TargetSha``"
        "- Started: ``$($StartedAt.ToString('u'))``"
        "- Finished: ``$([DateTimeOffset]::UtcNow.ToString('u'))``"
        "- Result: **$Result**"
    )
    if ($null -ne $PreviousImages) {
        $lines += '- Previous managed images:'
        foreach ($entry in $PreviousImages.GetEnumerator()) {
            $lines += "  - $($entry.Key): ``$($entry.Value)``"
        }
    }
    Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value ($lines -join [Environment]::NewLine)
}

Assert-ImageSha -Value $ImageSha
Assert-Kubeconfig

$startedAt = [DateTimeOffset]::UtcNow
$temporaryRoot = Join-Path `
    ([System.IO.Path]::GetTempPath()) `
    "edu-homework-grader-production-$([Guid]::NewGuid().ToString('N'))"
$previousImages = $null
$applyAttempted = $false

try {
    New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
    $previousImages = Get-ManagedImages

    $targetDestination = Join-Path $temporaryRoot 'target'
    if ([string]::IsNullOrWhiteSpace($ImageDigestsJson)) {
        $targetManifest = New-RenderedRelease `
            -Sha $ImageSha `
            -Destination $targetDestination
    }
    else {
        $targetImages = ConvertTo-ReleaseImagesFromDigests -DigestsJson $ImageDigestsJson
        $targetManifest = New-RenderedRelease `
            -ExactImages $targetImages `
            -Destination $targetDestination
    }
    $applyAttempted = $true
    Apply-RenderedRelease -ManifestPath $targetManifest
    Wait-ProductionHealthy

    Write-ReleaseSummary `
        -TargetSha $ImageSha `
        -PreviousImages $previousImages `
        -StartedAt $startedAt `
        -Result 'succeeded'
    Write-Output "Production release $ImageSha succeeded."
}
catch {
    $releaseFailure = $_

    if (-not $applyAttempted -or $null -eq $previousImages) {
        Write-ReleaseSummary `
            -TargetSha $ImageSha `
            -PreviousImages $previousImages `
            -StartedAt $startedAt `
            -Result 'failed before cluster mutation'
        throw $releaseFailure
    }

    $rollbackFailure = $null
    try {
        Restore-ManagedImages `
            -Images $previousImages `
            -Destination (Join-Path $temporaryRoot 'rollback')
    }
    catch {
        $rollbackFailure = $_
    }

    if ($null -eq $rollbackFailure) {
        Write-ReleaseSummary `
            -TargetSha $ImageSha `
            -PreviousImages $previousImages `
            -StartedAt $startedAt `
            -Result 'failed; rollback succeeded'
        throw "Production release $ImageSha failed; rollback succeeded."
    }

    Write-ReleaseSummary `
        -TargetSha $ImageSha `
        -PreviousImages $previousImages `
        -StartedAt $startedAt `
        -Result 'failed; rollback failed'
    throw "Production release $ImageSha failed; rollback failed."
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        $resolvedTemporaryRoot = [System.IO.Path]::GetFullPath($temporaryRoot)
        $resolvedSystemTemporaryPath = [System.IO.Path]::GetFullPath(
            [System.IO.Path]::GetTempPath()
        )
        if (-not $resolvedTemporaryRoot.StartsWith(
            $resolvedSystemTemporaryPath,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw 'Refusing to remove a temporary release directory outside the system temporary path.'
        }
        Remove-Item -LiteralPath $resolvedTemporaryRoot -Recurse -Force
    }
}
