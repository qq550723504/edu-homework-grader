Describe 'production alert manifest' {
    BeforeAll {
        $manifestPath = Join-Path $PSScriptRoot 'production-alert.yaml'
        $manifest = Get-Content -Raw -LiteralPath $manifestPath
    }

    It 'runs weekly with bounded execution and no overlap' {
        $manifest | Should -Match '(?m)^kind:\s*CronJob\s*$'
        $manifest | Should -Match '(?m)^\s{2}name:\s*production-alert\s*$'
        $manifest | Should -Match '(?m)^\s{2}schedule:\s*"30 4 \* \* 0"\s*$'
        $manifest | Should -Match '(?m)^\s{2}timeZone:\s*Asia/Singapore\s*$'
        $manifest | Should -Match '(?m)^\s{2}concurrencyPolicy:\s*Forbid\s*$'
        $manifest | Should -Match '(?m)^\s{6}backoffLimit:\s*0\s*$'
        $manifest | Should -Match '(?m)^\s{6}activeDeadlineSeconds:\s*300\s*$'
        $manifest | Should -Match '(?m)^\s{6}ttlSecondsAfterFinished:\s*86400\s*$'
    }

    It 'uses only the isolated SMTP Secret and checks each required dependency' {
        $manifest | Should -Match 'name:\s*production-alert-smtp'
        $manifest | Should -Match 'key:\s*ALERT_SMTP_AUTH_CODE'
        $manifest | Should -Match 'key:\s*DATABASE_URL'
        $manifest | Should -Match 'value:\s*https://edu\.getkr\.com/'
        $manifest | Should -Match 'value:\s*http://api:8000/infrastructure-ready'
        $manifest | Should -Match 'value:\s*http://grader:8010/health'
        $manifest | Should -Not -Match '(?i)ALERT_SMTP_AUTH_CODE:\s*[^$]'
        $manifest | Should -Not -Match '(?i)authorization[ _-]?code:\s*[^$]'
        $manifest | Should -Not -Match 'task-processor'
    }

    It 'runs the tested CLI from the API image placeholder' {
        $manifest | Should -Match 'ghcr\.io/qq550723504/edu-homework-grader-api:sha-not-published'
        $manifest | Should -Match 'edu_grader_api\.cli\.production_alert'
    }
}
