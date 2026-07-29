[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Namespace = 'edu-homework-grader',

    [Parameter(Mandatory = $true)]
    [string]$BackupTimestamp,

    [ValidateRange(1, 1800)]
    [int]$ReadyTimeoutSeconds = 300,

    [switch]$KeepRecoveryArtifacts,

    [switch]$ConfirmRecovery
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $ConfirmRecovery) {
    throw 'Pass -ConfirmRecovery to start an isolated PostgreSQL recovery drill.'
}

if ($BackupTimestamp -notmatch '^\d{8}T\d{6}Z$') {
    throw 'BackupTimestamp must use the yyyyMMddTHHmmssZ UTC format.'
}

$runId = "postgres-recovery-$BackupTimestamp".ToLowerInvariant()

function Invoke-Kubectl {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [string]$InputText
    )

    $global:LASTEXITCODE = 0
    if ($PSBoundParameters.ContainsKey('InputText')) {
        $result = $InputText | & kubectl @Arguments
    }
    else {
        $result = & kubectl @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "kubectl command failed with exit code $LASTEXITCODE."
    }
    return @($result)
}

if (-not $PSCmdlet.ShouldProcess("namespace/$Namespace pod/$runId", 'run isolated PostgreSQL recovery drill')) {
    return
}

$podManifest = @"
apiVersion: v1
kind: Pod
metadata:
  name: $runId
  namespace: $Namespace
  labels:
    app.kubernetes.io/name: postgres-recovery
    app.kubernetes.io/component: recovery-drill
spec:
  restartPolicy: Never
  volumes:
    - name: recovery
      emptyDir: {}
  initContainers:
    - name: fetch-backup
      image: rclone/rclone:1.71.0
      env:
        - name: COS_S3_ACCESS_KEY_ID
          valueFrom:
            secretKeyRef:
              name: edu-grader-backup-cos
              key: COS_S3_ACCESS_KEY_ID
        - name: COS_S3_SECRET_ACCESS_KEY
          valueFrom:
            secretKeyRef:
              name: edu-grader-backup-cos
              key: COS_S3_SECRET_ACCESS_KEY
        - name: COS_S3_ENDPOINT
          valueFrom:
            secretKeyRef:
              name: edu-grader-backup-cos
              key: COS_S3_ENDPOINT
        - name: COS_S3_REGION
          valueFrom:
            secretKeyRef:
              name: edu-grader-backup-cos
              key: COS_S3_REGION
        - name: COS_S3_BUCKET
          valueFrom:
            secretKeyRef:
              name: edu-grader-backup-cos
              key: COS_S3_BUCKET
      command:
        - /bin/sh
        - -ec
        - |
          set -eu
          umask 077
          cat > /tmp/rclone.conf <<EOF
          [cos]
          type = s3
          provider = TencentCOS
          access_key_id = `$COS_S3_ACCESS_KEY_ID
          secret_access_key = `$COS_S3_SECRET_ACCESS_KEY
          endpoint = `$COS_S3_ENDPOINT
          region = `$COS_S3_REGION
          EOF
          source="cos:`$COS_S3_BUCKET/edu-homework-grader/postgres/v1/$BackupTimestamp"
          rclone copy --config /tmp/rclone.conf --checksum "`$source" /recovery
          cd /recovery
          sha256sum -c edu_grader.dump.sha256
      volumeMounts:
        - name: recovery
          mountPath: /recovery
  containers:
    - name: postgres
      image: postgres:16-alpine
      env:
        - name: POSTGRES_DB
          value: edu_recovery
        - name: POSTGRES_USER
          value: edu_recovery
        - name: POSTGRES_HOST_AUTH_METHOD
          value: trust
      args:
        - postgres
        - -c
        - listen_addresses=127.0.0.1
      readinessProbe:
        exec:
          command: ["sh", "-c", "pg_isready -h 127.0.0.1 -U edu_recovery -d edu_recovery"]
      volumeMounts:
        - name: recovery
          mountPath: /recovery
"@

try {
    Invoke-Kubectl -Arguments @('apply', '--server-side', '--filename', '-') -InputText $podManifest | Out-Null
    Invoke-Kubectl -Arguments @(
        'wait', '--namespace', $Namespace,
        '--for=condition=Ready', "pod/$runId",
        "--timeout=$($ReadyTimeoutSeconds)s"
    ) | Out-Null

    Invoke-Kubectl -Arguments @(
        'exec', '--namespace', $Namespace, $runId, '--',
        'sh', '-ec',
        'pg_restore --clean --if-exists --no-owner --host=127.0.0.1 --username=edu_recovery --dbname=edu_recovery /recovery/edu_grader.dump'
    ) | Out-Null

    $validationSql = @"
SELECT 'question_versions', count(*) FROM question_versions;
SELECT 'assignments', count(*) FROM assignments;
SELECT 'student_attempts', count(*) FROM student_attempts;
SELECT 'grading_runs', count(*) FROM grading_runs;
SELECT 'student_guardian_consents', count(*) FROM student_guardian_consents;
SELECT 'audit_logs', count(*) FROM audit_logs;
"@
    $validation = Invoke-Kubectl -Arguments @(
        'exec', '--namespace', $Namespace, $runId, '--',
        'psql', '--host=127.0.0.1', '--username=edu_recovery', '--dbname=edu_recovery',
        '--tuples-only', '--no-align', '--command', $validationSql
    )

    Write-Information "Recovery drill completed for backup $BackupTimestamp using isolated pod $runId."
    foreach ($line in $validation) {
        if ($line -match '^(question_versions|assignments|student_attempts|grading_runs|student_guardian_consents|audit_logs)\|\d+$') {
            Write-Information $line
        }
    }
}
finally {
    if (-not $KeepRecoveryArtifacts) {
        & kubectl delete pod $runId --namespace $Namespace --ignore-not-found --wait=true | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Could not remove isolated recovery pod $runId."
        }
    }
}
