# Provider boundary P1 fix report

## Root cause

`GenerationRequest` validates `avoid_prompts` during normal construction, but
Pydantic's `model_copy(update=...)` does not revalidate the update. The OpenAI
provider previously serialized the copied request directly, so a PII-bearing
`avoid_prompts` value could reach the Responses API.

## Fix

- Extracted the existing `assert_deidentified_text` loop into
  `GenerationRequest.assert_deidentified_avoid_prompts()`.
- Kept the normal after-model constructor validator by having it call the
  extracted method.
- Rechecked `avoid_prompts` and constructed the request JSON before importing
  or constructing the OpenAI SDK client. A failed check becomes the sanitized
  `ProviderFailure(code="invalid_generation_request")`.

## Regression coverage

The generator contract test creates a valid request, uses `model_copy` to add
a phone number to `avoid_prompts`, and replaces `openai.OpenAI` with a sentinel.
It asserts that generation raises `invalid_generation_request` and that the
SDK sentinel is never invoked.

## Verification

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='packages/processor-policy/src;services/generator/src;apps/api/src'
python -m pytest -p no:cacheprovider services/generator/tests/test_contracts.py -k model_copy_avoid_prompts -q
python -m ruff check services/generator/src/edu_generator/contracts.py services/generator/src/edu_generator/openai_provider.py services/generator/tests/test_contracts.py
```

Result: `1 passed, 48 deselected`; Ruff completed with `All checks passed!`.
