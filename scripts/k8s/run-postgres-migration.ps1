[CmdletBinding()]
param(
    [string]$Namespace = 'edu-homework-grader',
    [Parameter(Mandatory)]
    [string]$Image,
    [switch]$ConfirmMigration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $ConfirmMigration) {
    throw 'Pass -ConfirmMigration to run the production Alembic migration Job.'
}

if ($Namespace -ne 'edu-homework-grader') {
    throw 'Namespace must be edu-homework-grader.'
}

if ($Image -notmatch '@sha256:[0-9a-f]{64}$') {
    throw 'The image reference must include an immutable sha256 digest.'
}

function Invoke-Kubectl {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & kubectl @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "kubectl $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

$jobName = 'postgres-migrate-' + (Get-Date -AsUTC -Format 'yyyyMMddHHmmss')
$manifest = @"
apiVersion: batch/v1
kind: Job
metadata:
  name: $jobName
  namespace: $Namespace
  labels:
    app.kubernetes.io/name: postgres-migrate
    app.kubernetes.io/part-of: edu-homework-grader
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 900
  ttlSecondsAfterFinished: 604800
  template:
    metadata:
      labels:
        app.kubernetes.io/name: postgres-migrate
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: migrate
          image: $Image
          imagePullPolicy: IfNotPresent
          command: ["python", "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"]
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: edu-grader-runtime
                  key: DATABASE_URL
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            readOnlyRootFilesystem: true
"@

$manifest | & kubectl apply --server-side -f -
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create migration Job $jobName."
}

Invoke-Kubectl -n $Namespace wait --for=condition=complete "job/$jobName" --timeout=15m
Invoke-Kubectl -n $Namespace logs "job/$jobName"
$revision = (& kubectl -n $Namespace exec statefulset/postgres -- psql -U edu_grader -d edu_grader -Atc 'select version_num from alembic_version').Trim()
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to read the Alembic revision from PostgreSQL.'
}

Write-Output "Alembic revision: $revision"
