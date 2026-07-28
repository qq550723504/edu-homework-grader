Describe 'create-prod-secrets' {
    BeforeAll {
        $scriptPath = Join-Path $PSScriptRoot 'create-prod-secrets.ps1'
    }

    It 'rejects a non-HTTPS production issuer before any Kubernetes write' {
        {
            & $scriptPath `
                -OidcIssuer 'http://issuer.example' `
                -GenerationGovernanceAdminSubjects @('admin-one', 'admin-two') `
                -OpenAiApiKey 'test-only-key' `
                -WhatIf
        } | Should -Throw 'OIDC issuer must use a non-local HTTPS URL in production.'
    }

    It 'requires at least two distinct governance administrator subjects' {
        {
            & $scriptPath `
                -OidcIssuer 'https://issuer.example' `
                -GenerationGovernanceAdminSubjects @('only-one') `
                -OpenAiApiKey 'test-only-key' `
                -WhatIf
        } | Should -Throw 'At least two distinct generation governance administrator subjects are required.'
    }

    It 'does not print secret-bearing values' {
        $source = Get-Content -Raw $scriptPath

        $source | Should -Not -Match 'Write-(Host|Output).*?(KEY|PASSWORD|TOKEN)'
        $source | Should -Match 'RandomNumberGenerator'
        $source | Should -Match 'kubectl create secret generic'
        $source | Should -Match 'REDIS_PASSWORD'
        $source | Should -Match 'REDIS_URL'
        $source | Should -Match 'NUXT_SESSION_PASSWORD'
        $source | Should -Match 'STUDENT_ACTIVATION_HMAC_KEY'
        $source | Should -Match 'KEYCLOAK_STUDENT_PROVISIONER_CLIENT_SECRET'
        $source | Should -Not -Match 'change-me'
        $source | Should -Not -Match 'development-only-change-me'
        $source | Should -Not -Match 'pilot-(admin|teacher|student)'
    }
}
