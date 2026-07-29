[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Namespace = 'edu-homework-grader',

    [Parameter(Mandatory = $true)]
    [string]$Bucket,

    [Parameter(Mandatory = $true)]
    [string]$Endpoint,

    [Parameter(Mandatory = $true)]
    [string]$Region,

    [string]$SecretName = 'edu-grader-backup-cos',

    [switch]$Replace,

    [switch]$ConfirmBackupCredential
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $ConfirmBackupCredential) {
    throw 'Pass -ConfirmBackupCredential to create or replace the COS backup Secret.'
}

try {
    $endpointUri = [Uri]$Endpoint
}
catch {
    throw 'COS endpoint must be an absolute HTTPS URL.'
}

if (-not $endpointUri.IsAbsoluteUri -or $endpointUri.Scheme -ne 'https' -or [string]::IsNullOrWhiteSpace($endpointUri.Host)) {
    throw 'COS endpoint must be an absolute HTTPS URL.'
}

if ([string]::IsNullOrWhiteSpace($Bucket) -or [string]::IsNullOrWhiteSpace($Region)) {
    throw 'COS bucket and region must not be empty.'
}

if (-not $PSCmdlet.ShouldProcess("namespace/$Namespace secret/$SecretName", 'create COS backup Secret')) {
    return
}

$existingSecret = & kubectl get secret $SecretName --namespace $Namespace --ignore-not-found --output name
if ($LASTEXITCODE -ne 0) {
    throw 'Kubernetes could not query the COS backup Secret.'
}
if ($existingSecret -and -not $Replace) {
    throw "Secret $SecretName already exists. Use -Replace only after a successful backup recovery plan."
}

$accessKeyId = Read-Host -Prompt 'COS access key ID'
if ([string]::IsNullOrWhiteSpace($accessKeyId)) {
    throw 'COS access key ID must not be empty.'
}

$secretKey = Read-Host -Prompt 'COS secret access key' -AsSecureString
$secretKeyBstr = [IntPtr]::Zero

try {
    $secretKeyBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secretKey)
    $secretKeyValue = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretKeyBstr)
    if ([string]::IsNullOrWhiteSpace($secretKeyValue)) {
        throw 'COS secret access key must not be empty.'
    }

    # kubectl create secret generic is used only as an in-memory manifest generator.
    $secretArguments = @(
        'create', 'secret', 'generic', $SecretName,
        '--namespace', $Namespace,
        "--from-literal=COS_S3_ACCESS_KEY_ID=$accessKeyId",
        "--from-literal=COS_S3_SECRET_ACCESS_KEY=$secretKeyValue",
        "--from-literal=COS_S3_ENDPOINT=$($endpointUri.AbsoluteUri.TrimEnd('/'))",
        "--from-literal=COS_S3_REGION=$Region",
        "--from-literal=COS_S3_BUCKET=$Bucket"
    )
    $manifest = & kubectl @secretArguments '--dry-run=client' '--output=yaml'
    if ($LASTEXITCODE -ne 0) {
        throw 'Kubernetes could not render the COS backup Secret manifest.'
    }

    $manifest | & kubectl apply --server-side --force-conflicts --filename -
    if ($LASTEXITCODE -ne 0) {
        throw 'Kubernetes could not apply the COS backup Secret.'
    }
}
finally {
    if ($secretKeyBstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretKeyBstr)
    }
}

Write-Information "Applied COS backup Secret $SecretName in namespace $Namespace."
