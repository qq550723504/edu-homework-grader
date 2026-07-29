[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Namespace = 'edu-homework-grader',
    [Parameter(Mandatory = $true)]
    [string]$OidcIssuer,
    [Parameter(Mandatory = $true)]
    [string[]]$GenerationGovernanceAdminSubjects,
    [Parameter(Mandatory = $true)]
    [AllowEmptyString()]
    [string]$OpenAiApiKey,
    [Parameter(Mandatory = $true)]
    [string]$EvaluationEvidenceHmacKey,
    [string]$SecretName = 'edu-grader-runtime',
    [switch]$Replace
)

$ErrorActionPreference = 'Stop'

function New-RandomSecret {
    param([int]$Bytes = 48)

    $buffer = [byte[]]::new($Bytes)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return [Convert]::ToBase64String($buffer)
}

$issuer = [Uri]$OidcIssuer
if ($issuer.Scheme -ne 'https' -or $issuer.Host -in @('localhost', '127.0.0.1', '::1')) {
    throw 'OIDC issuer must use a non-local HTTPS URL in production.'
}
$generationGovernanceAdminSubjects = @(
    $GenerationGovernanceAdminSubjects |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ } |
        Select-Object -Unique
)
if ($generationGovernanceAdminSubjects.Count -lt 2) {
    throw 'At least two distinct generation governance administrator subjects are required.'
}
if ([Text.Encoding]::UTF8.GetByteCount($EvaluationEvidenceHmacKey) -lt 32) {
    throw 'Evaluation evidence HMAC key must be at least 32 bytes.'
}

if (-not $PSCmdlet.ShouldProcess("namespace/$Namespace secret/$SecretName", 'create production runtime Secret')) {
    return
}

$existingSecret = & kubectl get secret $SecretName --namespace $Namespace --ignore-not-found --output name
if ($existingSecret -and -not $Replace) {
    throw "Secret $SecretName already exists. Use -Replace only after a successful rotation plan."
}

$postgresPassword = New-RandomSecret
$redisPassword = New-RandomSecret
$keycloakPostgresPassword = New-RandomSecret
$keycloakAdminPassword = New-RandomSecret
$auditHmacKey = New-RandomSecret
$studentActivationHmacKey = New-RandomSecret
$studentProvisionerClientSecret = New-RandomSecret
$nuxtSessionPassword = New-RandomSecret
$postgresPasswordForUrl = [Uri]::EscapeDataString($postgresPassword)
$redisPasswordForUrl = [Uri]::EscapeDataString($redisPassword)

$secretArguments = @(
    'create', 'secret', 'generic', $SecretName,
    '--namespace', $Namespace,
    "--from-literal=POSTGRES_PASSWORD=$postgresPassword",
    "--from-literal=DATABASE_URL=postgresql+psycopg://edu_grader:$postgresPasswordForUrl@postgres:5432/edu_grader",
    "--from-literal=REDIS_PASSWORD=$redisPassword",
    "--from-literal=REDIS_URL=redis://:$redisPasswordForUrl@redis:6379/0",
    "--from-literal=KEYCLOAK_POSTGRES_PASSWORD=$keycloakPostgresPassword",
    "--from-literal=KEYCLOAK_ADMIN_USERNAME=admin",
    "--from-literal=KEYCLOAK_ADMIN_PASSWORD=$keycloakAdminPassword",
    "--from-literal=AUDIT_HMAC_KEY=$auditHmacKey",
    "--from-literal=STUDENT_ACTIVATION_HMAC_KEY=$studentActivationHmacKey",
    "--from-literal=KEYCLOAK_STUDENT_PROVISIONER_CLIENT_SECRET=$studentProvisionerClientSecret",
    "--from-literal=NUXT_SESSION_PASSWORD=$nuxtSessionPassword",
    '--from-literal=AUDIT_HMAC_KEY_VERSION=k8s-1',
    '--from-literal=APP_ENV=production',
    "--from-literal=OIDC_ISSUER=$($issuer.AbsoluteUri.TrimEnd('/'))",
    '--from-literal=OIDC_AUDIENCE=edu-grader-api',
    '--from-literal=OIDC_SCHOOL_ID_CLAIM=school_id',
    '--from-literal=OIDC_TENANT_SLUG=pilot',
    '--from-literal=GRADER_BASE_URL=http://grader:8010',
    '--from-literal=PROCESSOR_ALLOWED_HOSTS=grader,languagetool',
    "--from-literal=GENERATION_GOVERNANCE_ADMIN_SUBJECTS=$($generationGovernanceAdminSubjects -join ',')",
    "--from-literal=OPENAI_API_KEY=$OpenAiApiKey",
    "--from-literal=EVALUATION_EVIDENCE_HMAC_KEY=$EvaluationEvidenceHmacKey"
)

# Use `kubectl create secret generic` as an in-memory manifest generator; values are never written to disk.
$manifest = & kubectl @secretArguments '--dry-run=client' '--output=yaml'
if ($LASTEXITCODE -ne 0) {
    throw 'Kubernetes could not render the production Secret manifest.'
}

$manifest | & kubectl apply --server-side --force-conflicts --filename -
if ($LASTEXITCODE -ne 0) {
    throw 'Kubernetes could not apply the production runtime Secret.'
}

Write-Information "Applied runtime Secret $SecretName in namespace $Namespace."
