Describe 'configure-production-alert-smtp' {
    BeforeAll {
        $scriptPath = Join-Path $PSScriptRoot 'configure-production-alert-smtp.ps1'
        $script = Get-Content -Raw -LiteralPath $scriptPath
    }

    It 'requires an explicit production confirmation and a masked prompt' {
        $script | Should -Match 'ConfirmProductionAlertSmtp'
        $script | Should -Match 'Read-Host.*AsSecureString'
        $script | Should -Match "Namespace = 'edu-homework-grader'"
    }

    It 'creates only the isolated SMTP Secret without echoing its authorization code' {
        $script | Should -Match 'name:\s*production-alert-smtp'
        $script | Should -Match 'ALERT_SMTP_AUTH_CODE'
        $script | Should -Not -Match 'Write-(Host|Output).*?(AUTH_CODE|AUTHORIZATION|PASSWORD|SECRET)'
        $script | Should -Not -Match '\[string\]\$AuthorizationCode'
    }
}
