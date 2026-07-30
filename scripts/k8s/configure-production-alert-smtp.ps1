[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Namespace = 'edu-homework-grader',
    [switch]$ConfirmProductionAlertSmtp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $ConfirmProductionAlertSmtp) {
    throw 'Pass -ConfirmProductionAlertSmtp to configure the production SMTP credential.'
}

if ($Namespace -ne 'edu-homework-grader') {
    throw 'The production SMTP credential is restricted to the edu-homework-grader namespace.'
}

if (-not $PSCmdlet.ShouldProcess("$Namespace/production-alert-smtp", 'create or replace SMTP Secret')) {
    return
}

$secureAuthorizationCode = Read-Host -Prompt 'QQ SMTP authorization code' -AsSecureString
$authorizationCodePointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR(
    $secureAuthorizationCode
)

try {
    $authorizationCode = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
        $authorizationCodePointer
    )
    if ([string]::IsNullOrWhiteSpace($authorizationCode)) {
        throw 'The SMTP authorization code must not be empty.'
    }

    @"
apiVersion: v1
kind: Secret
metadata:
  name: production-alert-smtp
  namespace: $Namespace
type: Opaque
stringData:
  ALERT_SMTP_HOST: smtp.qq.com
  ALERT_SMTP_PORT: "465"
  ALERT_SMTP_SENDER: 550723504@qq.com
  ALERT_SMTP_RECIPIENT: 550723504@qq.com
  ALERT_SMTP_AUTH_CODE: $authorizationCode
"@ | & kubectl apply --server-side --filename -
    if ($LASTEXITCODE -ne 0) {
        throw 'Kubernetes could not apply the production SMTP Secret.'
    }
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($authorizationCodePointer)
}

Write-Information "Configured production-alert-smtp in namespace $Namespace."
