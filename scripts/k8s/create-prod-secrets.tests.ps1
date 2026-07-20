$scriptPath = Join-Path $PSScriptRoot 'create-prod-secrets.ps1'

Describe 'create-prod-secrets' {
    It 'rejects a non-HTTPS production issuer before any Kubernetes write' {
        {
            & $scriptPath -OidcIssuer 'http://issuer.example' -WhatIf
        } | Should Throw 'OIDC issuer must use a non-local HTTPS URL in production.'
    }

    It 'does not print secret-bearing values' {
        $source = Get-Content -Raw $scriptPath

        $source | Should Not Match 'Write-(Host|Output).*?(KEY|PASSWORD|TOKEN)'
        $source | Should Match 'RandomNumberGenerator'
        $source | Should Match 'kubectl create secret generic'
        $source | Should Match 'REDIS_PASSWORD'
        $source | Should Match 'REDIS_URL'
        $source | Should Match 'NUXT_SESSION_PASSWORD'
        $source | Should Not Match 'change-me'
        $source | Should Not Match 'development-only-change-me'
        $source | Should Not Match 'pilot-(admin|teacher|student)'
    }
}
