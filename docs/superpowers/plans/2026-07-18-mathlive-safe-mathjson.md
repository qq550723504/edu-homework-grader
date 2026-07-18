# MathLive and Safe MathJSON Implementation Plan

> For agentic workers: use superpowers:subagent-driven-development or superpowers:executing-plans to execute this plan task-by-task. Steps use checkbox syntax.

Goal: Implement Issue #5 with MathLive student input, server-owned MathJSON normalization, bounded deterministic math grading, and resource-limited Grader execution.

Architecture: Preserve M2@1 and add M2@2. The browser emits display LaTeX plus MathJSON; the Grader validates a restricted dialect and converts it to the platform AST; the API persists the server-produced AST next to the display representation. Each automatic M2@2 grade runs in a constrained child process in the existing Grader container. Unsafe or ambiguous input returns needs_review.

Tech Stack: Nuxt 4/Vue 3, MathLive, @cortex-js/compute-engine, FastAPI, Pydantic, SymPy, SQLAlchemy, Docker Compose, pytest, Vitest.

## Global Constraints

- Preserve M2@1 policy and grading behavior. MathLive questions use M2@2.
- Do not invoke sympy.parse_expr(), evaluate LaTeX, compile MathJSON, or execute client-provided text.
- Accept only Add, Multiply, Negate, Divide, Power, Rational, finite bounded numbers, and question-whitelisted ASCII variables.
- Enforce depth 20, node count 100, variadic arity 12, 64 integer digits, 32 fractional digits, and integer exponents -10 through 10.
- Symbolic denominators, equations, solver forms, invalid input, timeout, and resource exhaustion produce needs_review, never an automatic zero.
- Limit the Grader container CPU, memory, and PIDs. Parent process enforces a wall-clock deadline.
- Add at least 100 explicit M2@2 golden cases covering correct, partial, incorrect, boundary, invalid, and adversarial input.

---

## File Structure

- services/grader/src/edu_grader/mathjson.py: MathJSON whitelist and AST normalizer.
- services/grader/src/edu_grader/math_ast.py: M2@2 equivalence, form, and domain behavior.
- services/grader/src/edu_grader/execution.py: child-process lifecycle and resource-limit outcomes.
- services/grader/src/edu_grader/math_worker.py: worker entry point.
- services/grader/tests/fixtures/m2_mathjson_golden.json: fixed 100+ case fixture.
- apps/api/src/edu_grader_api/policies.py: M2@2 policy schema.
- apps/api/src/edu_grader_api/services/grader.py: normalizer and M2@2 HTTP adapters.
- apps/api/src/edu_grader_api/services/assignments.py: server normalization before persistence.
- apps/api/src/edu_grader_api/routers/assignments.py: safe input projection and typed errors.
- apps/web/app/lib/math-answer.ts: browser-independent answer helpers.
- apps/web/app/components/MathAnswerField.client.vue: MathLive wrapper.
- apps/web/app/pages/student/assignments/[assignmentId].vue: conditional math input and outbox path.
- compose.yaml and README.md: deployment limits and operations.

### Task 1: Normalize restricted MathJSON

Files:
- Create: services/grader/src/edu_grader/mathjson.py
- Create: services/grader/tests/test_mathjson.py

Interfaces:
- Produces MathJsonValidationError(code: str, message: str).
- Produces normalize_mathjson(value: object, variables: list[str]) -> dict[str, object].
- Output uses existing AST shapes: number, symbol, add, mul, neg, div, pow.

- [ ] Step 1: Write the failing whitelist tests.

~~~
from edu_grader.mathjson import MathJsonValidationError, normalize_mathjson

def test_normalizes_whitelisted_mathjson() -> None:
    assert normalize_mathjson(["Add", ["Multiply", 2, "x"], 6], ["x"]) == {
        "type": "add",
        "args": [
            {"type": "mul", "args": [
                {"type": "number", "value": "2"},
                {"type": "symbol", "name": "x"},
            ]},
            {"type": "number", "value": "6"},
        ],
    }

def test_rejects_control_node() -> None:
    with pytest.raises(MathJsonValidationError, match="unsupported_operator"):
        normalize_mathjson(["Assign", "x", 1], ["x"])
~~~

- [ ] Step 2: Verify RED.

Run: python -m pytest services/grader/tests/test_mathjson.py -q

Expected: import failure because edu_grader.mathjson is absent.

- [ ] Step 3: Implement the recursive parser.

~~~
class MathJsonValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)

def normalize_mathjson(value: object, variables: list[str]) -> dict[str, object]:
    return _normalize(value, _Context(set(variables)), depth=0)
~~~

Count every node before descent. Translate the six allowed operators one-way into the internal AST. Accept only JSON number literals and bounded number-string shorthand. Reject object metadata, non-finite values, unknown symbols, bad arity, zero numeric denominator, and every unlisted operator. Enforce every global numeric and structural bound in this module before SymPy is reached.

- [ ] Step 4: Add adversarial limit tests.

Add assertions for depth 21, 101 nodes, 13 Add arguments, 65 integer digits, 33 fractional digits, exponent 11, NaN, Infinity, Equal, Parse, object number metadata, unknown z, Divide(1, 0), and Divide(1, x). Each assertion checks its exact stable error code.

- [ ] Step 5: Verify GREEN and commit.

Run: python -m pytest services/grader/tests/test_mathjson.py -q

~~~bash
git add services/grader/src/edu_grader/mathjson.py services/grader/tests/test_mathjson.py
git commit -m "feat(grader): normalize restricted MathJSON"
~~~

### Task 2: Grade M2@2 safely and add the golden suite

Files:
- Modify: services/grader/src/edu_grader/math_ast.py
- Modify: services/grader/tests/test_math.py
- Create: services/grader/tests/fixtures/m2_mathjson_golden.json
- Create: services/grader/tests/test_math_golden.py

Interfaces:
- Consumes normalize_mathjson() from Task 1.
- Produces grade_mathjson_expression(student_mathjson: object, expected_mathjson: object, variables: list[str], required_form: str | None, form_score: float, max_score: float) -> GradingResult.
- Produces is_expanded_ast(node: dict[str, object]) -> bool.

- [ ] Step 1: Write failing review and form tests.

~~~
def test_symbolic_denominator_requires_review() -> None:
    result = grade_mathjson_expression(
        ["Divide", 1, "x"], ["Divide", 1, "x"], ["x"], None, 0, 1
    )
    assert result.decision == "needs_review"
    assert result.requires_review is True
    assert result.criteria[0].code == "domain_ambiguity"

def test_product_containing_sum_is_not_expanded() -> None:
    assert is_expanded_ast({
        "type": "mul",
        "args": [
            {"type": "number", "value": "2"},
            {"type": "add", "args": [
                {"type": "symbol", "name": "x"},
                {"type": "number", "value": "3"},
            ]},
        ],
    }) is False
~~~

- [ ] Step 2: Verify RED.

Run: python -m pytest services/grader/tests/test_math.py -q

Expected: failure because grade_mathjson_expression does not exist.

- [ ] Step 3: Implement M2@2 grading.

Normalize expected and student values first. Return needs_review before SymPy for normalizer errors, symbolic denominators, equations, and powers of additive bases. For remaining input, reuse build_expression() and bounded symbolic difference calculation. is_expanded_ast() rejects a multiply containing an add factor and a power with an add base. Every unsafe result uses GradingResult with decision needs_review, score 0, confidence 0, requires_review true, a stable first Criterion code, and Chinese math-input feedback.

- [ ] Step 4: Add and parameterize 100+ golden rows.

Each row has name, student, expected, variables, required_form, form_score, max_score, decision, score, and criterion_code. Include at least 25 accepted polynomial rows, 15 partial expanded-form rows, 20 incorrect rows, 10 constant-denominator rows, 10 malformed/unknown operator rows, 10 structural-limit rows, and 10 zero/symbolic-denominator rows. Parametrize the fixture and assert decision, score, requires_review, and first criterion code.

- [ ] Step 5: Verify GREEN and commit.

Run: python -m pytest services/grader/tests -q

~~~bash
git add services/grader/src/edu_grader/math_ast.py services/grader/tests/test_math.py services/grader/tests/test_math_golden.py services/grader/tests/fixtures/m2_mathjson_golden.json
git commit -m "feat(grader): grade bounded MathJSON expressions"
~~~

### Task 3: Isolate M2 execution and publish Grader endpoints

Files:
- Create: services/grader/src/edu_grader/execution.py
- Create: services/grader/src/edu_grader/math_worker.py
- Modify: services/grader/src/edu_grader/main.py
- Create: services/grader/tests/test_math_execution.py

Interfaces:
- Produces MathExecutionLimits(cpu_seconds: int, memory_bytes: int, timeout_seconds: float).
- Produces run_math_expression(request: dict[str, object], limits: MathExecutionLimits) -> GradingResult.
- Adds POST /v1/normalize/mathjson and POST /v1/grade/math/expression-v2.

- [ ] Step 1: Write failing timeout tests.

~~~
def test_timeout_becomes_review_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution, "_join_worker", lambda *_: None)
    result = execution.run_math_expression({"student": ["Add", 1, 1]}, _limits())
    assert result.decision == "needs_review"
    assert result.criteria[0].code == "execution_timeout"
~~~

Also add HTTP tests: normalizer returns ast, Assign returns a typed code, and timeout returns status 200 plus a review GradingResult.

- [ ] Step 2: Verify RED.

Run: python -m pytest services/grader/tests/test_math_execution.py -q

Expected: import failure.

- [ ] Step 3: Implement parent/worker boundary.

The parent sends only JSON-safe rule and AST data to a spawned process, joins for timeout_seconds, terminates a live child, and maps abnormal exit to execution_resource_limit. The child applies RLIMIT_CPU and RLIMIT_AS when resource exists, calls Task 2, and sends GradingResult.model_dump() through a one-way pipe. Parent wall-clock termination must work on Windows too.

- [ ] Step 4: Verify GREEN and commit.

Run: python -m pytest services/grader/tests -q

~~~bash
git add services/grader/src/edu_grader/execution.py services/grader/src/edu_grader/math_worker.py services/grader/src/edu_grader/main.py services/grader/tests/test_math_execution.py
git commit -m "feat(grader): isolate bounded math evaluation"
~~~

### Task 4: Register M2@2 and connect the API to the Grader

Files:
- Modify: apps/api/src/edu_grader_api/policies.py
- Modify: apps/api/src/edu_grader_api/services/grader.py
- Modify: apps/api/src/edu_grader_api/services/questions.py
- Create: apps/api/tests/test_math_policy_v2.py

Interfaces:
- Adds M2_POLICY_V2 to POLICY_SCHEMAS[(M2, 2)].
- Produces MathAnswerNormalizationError(code: str, message: str).
- Produces HttpGraderClient.normalize_math_answer(answer_json: dict[str, object]) -> dict[str, object].

- [ ] Step 1: Write failing policy/client tests.

~~~
def test_m2_v2_accepts_mathjson_and_m2_v1_remains_supported() -> None:
    assert validate_policy("M2", "2", {"expected": ["Add", 1, "x"], "variables": ["x"]}) == []
    assert validate_policy("M2", "1", {"expected": {"type": "symbol", "name": "x"}}) == []
    assert validate_policy("M2", "2", {"expected": "x"})
~~~

Mock httpx and assert normalization calls /v1/normalize/mathjson. Assert M2@2 test execution uses /v1/grade/math/expression-v2.

- [ ] Step 2: Verify RED.

Run: python -m pytest apps/api/tests/test_math_policy_v2.py -q

- [ ] Step 3: Implement schema and adapters.

M2@2 requires expected and permits bounded variables, required_form, form_score, and max_score. Keep expected as JSON because the Grader owns dialect validation. Keep M2@1 untouched. Map non-2xx normalizer responses into MathAnswerNormalizationError. Extend required pre-publish categories only for M2@2 with invalid_mathjson and resource_limit.

- [ ] Step 4: Verify GREEN and commit.

Run: python -m pytest apps/api/tests/test_math_policy_v2.py apps/api/tests/test_question_runs.py apps/api/tests/test_questions.py -q

~~~bash
git add apps/api/src/edu_grader_api/policies.py apps/api/src/edu_grader_api/services/grader.py apps/api/src/edu_grader_api/services/questions.py apps/api/tests/test_math_policy_v2.py
git commit -m "feat(api): add versioned MathJSON policy"
~~~

### Task 5: Persist normalized answers and expose safe metadata

Files:
- Modify: apps/api/src/edu_grader_api/services/assignments.py
- Modify: apps/api/src/edu_grader_api/routers/assignments.py
- Create: apps/api/tests/test_math_answers.py

Interfaces:
- Adds MathAnswerNormalizer protocol with normalize_math_answer(answer_json: dict[str, object]) -> dict[str, object].
- Extends save_answer(..., answer_normalizer: MathAnswerNormalizer | None = None) -> AttemptAnswer.
- Adds item input descriptor: M2@2 uses mathjson-v1; every other item uses text.

- [ ] Step 1: Write failing detail and persistence tests.

~~~
def test_m2_v2_detail_redacts_expected_and_exposes_safe_input(client, session) -> None:
    item = client.get(student_assignment_url, headers=student_headers).json()["items"][0]
    assert item["input"] == {
        "kind": "mathjson-v1", "variables": ["x"], "required_form": "expanded"
    }
    assert "expected" not in item

def test_m2_v2_save_persists_server_ast(client, monkeypatch) -> None:
    monkeypatch.setattr(assignments, "HttpGraderClient", FakeNormalizerClient)
    saved = client.put(answer_url, headers=student_headers, json={"answer": math_answer, "version": 0})
    assert saved.json()["answer"]["ast"]["type"] == "add"
~~~

Also test malicious raw payload 422 with code unsupported_operator, stale-version preservation of normalized data, and unchanged M1 input kind text.

- [ ] Step 2: Verify RED.

Run: python -m pytest apps/api/tests/test_math_answers.py -q

- [ ] Step 3: Implement normalization at the persistence boundary.

For M2@2 require format mathjson-v1, bounded latex, and mathjson. Normalize before optimistic update and persist exactly format, latex, mathjson, and server ast. Map MathAnswerNormalizationError to a structured 422 code/message response. Do not normalize M1 or M2@1. Derive the detail descriptor from variables and required_form only: never expected, scores, policy IDs, or grader output.

- [ ] Step 4: Verify GREEN and commit.

Run: python -m pytest apps/api/tests/test_assignments.py apps/api/tests/test_math_answers.py -q

~~~bash
git add apps/api/src/edu_grader_api/services/assignments.py apps/api/src/edu_grader_api/routers/assignments.py apps/api/tests/test_math_answers.py
git commit -m "feat(api): persist normalized MathJSON answers"
~~~

### Task 6: Build the MathLive client path

Files:
- Modify: apps/web/package.json
- Modify: apps/web/package-lock.json
- Create: apps/web/app/lib/math-answer.ts
- Create: apps/web/app/components/MathAnswerField.client.vue
- Modify: apps/web/app/pages/student/assignments/[assignmentId].vue
- Create: apps/web/tests/math-answer.test.ts

Interfaces:
- Produces type MathAnswer = { format: "mathjson-v1"; latex: string; mathjson: unknown }.
- Produces toMathAnswer(field: { value: string; getValue(format: "math-json"): string }): MathAnswer | null.
- Component emits update:modelValue with MathAnswer | null.

- [ ] Step 1: Write failing payload tests.

~~~
it("keeps LaTeX and parses MathJSON", () => {
  expect(toMathAnswer({
    value: "\\frac{1}{2}",
    getValue: () => '["Rational",1,2]'
  })).toEqual({
    format: "mathjson-v1", latex: "\\frac{1}{2}", mathjson: ["Rational", 1, 2]
  })
})

it("does not queue malformed MathJSON", () => {
  expect(toMathAnswer({ value: "x+", getValue: () => "not-json" })).toBeNull()
})
~~~

- [ ] Step 2: Verify RED.

Run: npm test -- math-answer.test.ts

- [ ] Step 3: Install and integrate MathLive.

Run: npm install mathlive @cortex-js/compute-engine

toMathAnswer() parses only getValue("math-json") and returns null for empty LaTeX or invalid JSON. The client component dynamically imports both packages in onMounted, mounts math-field, sets mathVirtualKeyboardPolicy auto, configures numeric, symbols, and alphabetic layouts, and emits only valid MathAnswer objects. It must not import MathLive during SSR evaluation.

Replace the textarea only when currentItem.input.kind is mathjson-v1. Keep text input behavior unchanged. An incomplete field displays inline feedback and remains out of the Dexie sync queue.

- [ ] Step 4: Verify GREEN and commit.

Run: npm test && npm run build

~~~bash
git add apps/web/package.json apps/web/package-lock.json apps/web/app/lib/math-answer.ts apps/web/app/components/MathAnswerField.client.vue apps/web/app/pages/student/assignments/[assignmentId].vue apps/web/tests/math-answer.test.ts
git commit -m "feat(web): add MathLive answer input"
~~~

### Task 7: Configure limits, document operation, and run integration verification

Files:
- Modify: compose.yaml
- Modify: README.md
- Modify: services/grader/src/edu_grader/execution.py
- Modify: services/grader/tests/test_math_execution.py

Interfaces:
- Defines GRADER_MATH_CPU_SECONDS, GRADER_MATH_MEMORY_BYTES, and GRADER_MATH_TIMEOUT_SECONDS.
- Configures Grader cpus 0.50, mem_limit 256m, and pids_limit 64.

- [ ] Step 1: Write the failing default-limit test.

~~~
def test_default_execution_limits_are_bounded() -> None:
    assert load_math_execution_limits({}) == MathExecutionLimits(
        cpu_seconds=1, memory_bytes=134_217_728, timeout_seconds=1.0
    )
~~~

- [ ] Step 2: Verify RED.

Run: python -m pytest services/grader/tests/test_math_execution.py -q

- [ ] Step 3: Implement configuration and docs.

Read only the three named variables, reject non-positive values at Grader startup, and use the asserted defaults. Add Compose limits under the existing grader service without changing ports. Document M2@1 versus M2@2, resource values, golden-suite command, and Compose validation in README.

- [ ] Step 4: Run final verification.

~~~powershell
python -m pytest apps/api/tests services/grader/tests -q
python -m ruff check apps/api services/grader
python -m ruff format --check apps/api services/grader
Push-Location apps/web; npm test; npm run build; Pop-Location
docker compose config
git diff --check
~~~

Expected: tests, lint, format, Nuxt production build, and Compose validation all pass.

- [ ] Step 5: Commit.

~~~bash
git add compose.yaml README.md services/grader/src/edu_grader/execution.py services/grader/tests/test_math_execution.py
git commit -m "docs: document bounded math grading"
~~~

## Plan self-review

- Spec coverage: Tasks 1–3 provide the whitelist, limits, safe grading, review outcomes, worker boundary, and golden fixture. Tasks 4–5 provide versioned policy, categories, normalization, persistence, and redacted item metadata. Task 6 provides MathLive and mobile keyboard with existing outbox integration. Task 7 provides deploy limits, documentation, and complete verification.
- Placeholder scan: every task lists file paths, interfaces, failing tests, verification commands, implementation behavior, and commit scope.
- Type consistency: mathjson-v1 is emitted in Task 6, persisted in Task 5 through Task 4, normalized in Task 1, and graded in Tasks 2–3. Unsafe outcomes consistently use the existing GradingResult decision needs_review.

