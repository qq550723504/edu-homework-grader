Describe 'production Kustomize labels' {
    It 'keeps the shared ownership label out of StatefulSet selectors' {
        $kustomization = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'kustomization.yaml')

        $kustomization | Should -Match 'app\.kubernetes\.io/part-of: edu-homework-grader'
        $kustomization | Should -Not -Match 'includeSelectors:\s*true'
    }
}
