[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Namespace = 'edu-homework-grader',
    [string]$RuntimeSecretName = 'edu-grader-runtime',
    [string]$EvaluatorSecretName = 'operational-evaluation-runtime',
    [Parameter(Mandatory = $true)]
    [string]$GitHubOperationalEvaluationAudience,
    [Parameter(Mandatory = $true)]
    [string]$GitHubOperationalEvaluationRepositoryId,
    [Parameter(Mandatory = $true)]
    [string]$GitHubOperationalEvaluationOwnerId,
    [Parameter(Mandatory = $true)]
    [string]$GitHubOperationalEvaluationWorkflowRef,
    [Parameter(Mandatory = $true)]
    [string]$OperationalEvaluationExecutorImage,
    [string]$OperationalEvaluationCallbackBaseUrl = 'http://api:8000',
    [switch]$Replace
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function New-RandomSecret {
    param([int]$Bytes = 48)

    $buffer = [byte[]]::new($Bytes)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return [Convert]::ToBase64String($buffer)
}

function Get-SecretText {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Key
    )

    $encoded = & kubectl get secret $Name --namespace $Namespace --output "jsonpath={.data.$Key}"
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($encoded)) {
        throw "Required key $Key is missing from Secret $Name."
    }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
}

if ($GitHubOperationalEvaluationRepositoryId -notmatch '^\d+$') {
    throw 'GitHub operational evaluation repository ID must be numeric.'
}
if ($GitHubOperationalEvaluationOwnerId -notmatch '^\d+$') {
    throw 'GitHub operational evaluation owner ID must be numeric.'
}
if ($GitHubOperationalEvaluationWorkflowRef -notmatch '^[^/\s]+/[^/\s]+/\.github/workflows/ai-evaluation-operational\.yml@refs/heads/main$') {
    throw 'GitHub operational evaluation workflow reference must target ai-evaluation-operational on main.'
}
if ([string]::IsNullOrWhiteSpace($GitHubOperationalEvaluationAudience)) {
    throw 'GitHub operational evaluation audience is required.'
}
if ($OperationalEvaluationExecutorImage -notmatch '@sha256:[0-9a-f]{64}$') {
    throw 'Operational evaluation executor image must be digest pinned.'
}
$callbackUri = [Uri]$OperationalEvaluationCallbackBaseUrl
if ($callbackUri.Scheme -notin @('http', 'https') -or [string]::IsNullOrWhiteSpace($callbackUri.Host)) {
    throw 'Operational evaluation callback base URL must be an HTTP(S) URL.'
}

if (-not $PSCmdlet.ShouldProcess("namespace/$Namespace", 'bootstrap operational evaluation runtime')) {
    return
}

$existingEvaluatorSecret = & kubectl get secret $EvaluatorSecretName --namespace $Namespace --ignore-not-found --output name
if ($LASTEXITCODE -ne 0) {
    throw "Kubernetes could not query Secret $EvaluatorSecretName."
}
if ($existingEvaluatorSecret -and -not $Replace) {
    throw "Secret $EvaluatorSecretName already exists. Use -Replace only as a coordinated credential rotation."
}

$evaluationHmacKey = Get-SecretText -Name $RuntimeSecretName -Key 'EVALUATION_EVIDENCE_HMAC_KEY'
if ([Text.Encoding]::UTF8.GetByteCount($evaluationHmacKey) -lt 32) {
    throw 'The existing evaluation evidence HMAC key must be at least 32 bytes.'
}

$readerPassword = New-RandomSecret
$readerPasswordForUrl = [Uri]::EscapeDataString($readerPassword)
$readerBootstrapSql = @"
\set ON_ERROR_STOP on
\set reader_password $readerPassword
SELECT CASE
  WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'operational_evaluation_reader')
    THEN format('ALTER ROLE operational_evaluation_reader LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS', :'reader_password')
  ELSE format('CREATE ROLE operational_evaluation_reader LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS', :'reader_password')
END;
\gexec
GRANT CONNECT ON DATABASE edu_grader TO operational_evaluation_reader;
GRANT USAGE ON SCHEMA public TO operational_evaluation_reader;
REVOKE CREATE ON SCHEMA public FROM operational_evaluation_reader;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM operational_evaluation_reader;
GRANT SELECT ON TABLE public.generation_jobs, public.generation_attempts, public.generated_question_drafts,
  public.generated_question_draft_revisions, public.generated_question_review_decisions,
  public.generation_validation_runs, public.generation_governance_entries,
  public.curriculum_objective_revisions, public.curriculum_objectives,
  public.curriculum_grade_mappings, public.curriculum_profiles, public.question_versions
  TO operational_evaluation_reader;
"@

$readerBootstrapSql | & kubectl exec --namespace $Namespace statefulset/postgres '--stdin' '--' `
    'sh' '-ec' 'PGPASSWORD="$POSTGRES_PASSWORD" exec psql --set=ON_ERROR_STOP=1 --username=edu_grader --dbname=edu_grader'
if ($LASTEXITCODE -ne 0) {
    throw 'PostgreSQL could not configure the operational evaluation read-only role.'
}

$writePrivilegeCheck = @"
SELECT EXISTS (
  SELECT 1
  FROM (VALUES
    ('public.generation_jobs'), ('public.generation_attempts'), ('public.generated_question_drafts'),
    ('public.generated_question_draft_revisions'), ('public.generated_question_review_decisions'),
    ('public.generation_validation_runs'), ('public.generation_governance_entries'),
    ('public.curriculum_objective_revisions'), ('public.curriculum_objectives'),
    ('public.curriculum_grade_mappings'), ('public.curriculum_profiles'), ('public.question_versions')
  ) AS evaluation_tables(name)
  WHERE has_table_privilege('operational_evaluation_reader', name, 'INSERT')
     OR has_table_privilege('operational_evaluation_reader', name, 'UPDATE')
     OR has_table_privilege('operational_evaluation_reader', name, 'DELETE')
);
"@
$hasWritePrivilege = $writePrivilegeCheck | & kubectl exec --namespace $Namespace statefulset/postgres '--stdin' '--' `
    'sh' '-ec' 'PGPASSWORD="$POSTGRES_PASSWORD" exec psql --set=ON_ERROR_STOP=1 --tuples-only --no-align --username=edu_grader --dbname=edu_grader'
if ($LASTEXITCODE -ne 0 -or ($hasWritePrivilege -join '').Trim() -ne 'f') {
    throw 'Operational evaluation reader unexpectedly has write privileges.'
}

$evaluatorSecretArguments = @(
    'create', 'secret', 'generic', $EvaluatorSecretName,
    '--namespace', $Namespace,
    "--from-literal=DATABASE_URL=postgresql+psycopg://operational_evaluation_reader:$readerPasswordForUrl@postgres:5432/edu_grader",
    "--from-literal=EVALUATION_EVIDENCE_HMAC_KEY=$evaluationHmacKey"
)
$evaluatorManifest = & kubectl @evaluatorSecretArguments '--dry-run=client' '--output=yaml'
if ($LASTEXITCODE -ne 0) {
    throw 'Kubernetes could not render the operational evaluation runtime Secret.'
}
$evaluatorManifest | & kubectl apply --server-side --force-conflicts --filename -
if ($LASTEXITCODE -ne 0) {
    throw 'Kubernetes could not apply the operational evaluation runtime Secret.'
}

$trustSecretArguments = @(
    'create', 'secret', 'generic', $RuntimeSecretName,
    '--namespace', $Namespace,
    "--from-literal=GITHUB_OPERATIONAL_EVALUATION_AUDIENCE=$GitHubOperationalEvaluationAudience",
    "--from-literal=GITHUB_OPERATIONAL_EVALUATION_REPOSITORY_ID=$GitHubOperationalEvaluationRepositoryId",
    "--from-literal=GITHUB_OPERATIONAL_EVALUATION_OWNER_ID=$GitHubOperationalEvaluationOwnerId",
    "--from-literal=GITHUB_OPERATIONAL_EVALUATION_WORKFLOW_REF=$GitHubOperationalEvaluationWorkflowRef"
)
$trustManifest = & kubectl @trustSecretArguments '--dry-run=client' '--output=yaml'
if ($LASTEXITCODE -ne 0) {
    throw 'Kubernetes could not render GitHub operational evaluation trust configuration.'
}
$trustManifest | & kubectl apply --server-side --force-conflicts --filename -
if ($LASTEXITCODE -ne 0) {
    throw 'Kubernetes could not apply GitHub operational evaluation trust configuration.'
}

Write-Information "Bootstrapped operational evaluation runtime in namespace $Namespace."
