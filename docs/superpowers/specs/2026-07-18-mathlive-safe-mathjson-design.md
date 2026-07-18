# MathLive and Safe MathJSON Design

## Goal

Implement Issue #5: let students enter algebra with MathLive, persist display and structured representations, and grade a deliberately small, bounded mathematics language without accepting executable expression strings.

## Scope

This slice adds a MathLive input path for new M2 expression questions, a versioned M2 policy, a MathJSON-to-internal-AST validator, bounded deterministic expression grading, and a resource-limited Grader execution boundary. It also adds a golden suite of at least 100 mathematical cases.

It does not add a teacher review queue or grade publication UI. The Grader marks unsafe, unsupported, invalid, and resource-limited requests as `needs_review`; Issue #7 will materialize those results into a teacher workflow.

## Selected approach

Use MathLive and the Cortex Compute Engine in the browser. The browser records both the MathLive LaTeX value for display and its MathJSON value for structured transport. The API treats both as untrusted input: it never parses LaTeX and does not run the Compute Engine or SymPy parser on input strings.

The API recursively validates a small MathJSON dialect and converts it into the existing platform-owned internal AST. Only that internal AST reaches SymPy operations inside the Grader. The Grader remains the existing Docker service, but each math evaluation runs in an isolated child process with configurable CPU, memory, and wall-clock limits; Compose also limits the service container.

## Versioned contracts

Existing M2@1 questions retain their current internal-AST rule shape and behavior. New MathLive-capable questions use M2@2, so published M2@1 versions remain reproducible.

An M2@2 rule contains:

```json
{
  "expected": ["Add", ["Multiply", 2, "x"], 6],
  "variables": ["x"],
  "required_form": "expanded",
  "form_score": 1,
  "max_score": 5
}
```

The student answer contract is:

```json
{
  "format": "mathjson-v1",
  "latex": "2x+6",
  "mathjson": ["Add", ["Multiply", 2, "x"], 6]
}
```

On successful API validation, the persisted answer additionally contains the server-produced `ast` field. The original MathJSON and LaTeX remain for display and audit; downstream grading uses only `ast`.

The student assignment detail projection exposes only an input descriptor such as:

```json
{
  "kind": "mathjson-v1",
  "variables": ["x"],
  "required_form": "expanded"
}
```

It never exposes the expected answer, rubric internals, or score breakdown.

## Safe MathJSON dialect

The server accepts shorthand MathJSON only: finite JSON numbers, ASCII symbols allowed by the question, and function arrays. It rejects metadata objects and all strings that are not question-allowed symbols or bounded numeric literals.

Allowed operators are `Add`, `Multiply`, `Negate`, `Divide`, `Power`, and `Rational`. They map one-way to the platform internal nodes `add`, `mul`, `neg`, `div`, `pow`, and `number`. The server rejects Compute Engine control, parser, assignment, declaration, function, collection, equation, set, calculus, and styling operators, including `Assign`, `Declare`, `Parse`, `Apply`, `Equal`, `List`, and `Error`.

Every tree is limited to depth 20, 100 nodes, 12 operands per variadic operator, 64 integer digits, 32 fractional digits, and integer exponents from -10 through 10. Numbers must be finite. Unknown symbols, zero numeric denominators, invalid arity, and all unsupported representations produce a structured `needs_review` result rather than a zero score.

Symbolic denominators and equation or solving forms are also `needs_review` in this first release. This makes the domain policy explicit: only polynomial expressions and expressions with non-zero constant denominators receive automatic equivalence grading. It avoids claiming equivalence where a cancelled factor would create a different domain or where transformations could introduce extraneous roots.

`expanded` is determined from the preserved internal AST shape: a product containing an additive factor and a power whose base is additive are not expanded. It is not inferred only from a post-simplification SymPy value.

## Execution and error behavior

The public Grader endpoint returns `GradingResult` for every mathematical request. Validation failures, unsupported dialect features, domain ambiguity, worker timeout, and worker resource exhaustion have decision `needs_review`, `requires_review: true`, a stable criterion code, and a human-readable feedback message. They do not escape as an unstructured FastAPI error and never award an automatic zero.

The parent process validates the input before spawning the worker. The worker receives only a normalized internal-AST request and rule, applies platform CPU and address-space limits when supported, and is terminated by the parent when its wall-clock deadline expires. Compose config sets the Grader service CPU, memory, and PID ceilings. The API's HTTP client has a lower bounded read timeout and treats an unavailable Grader as a visible grading error.

## Student experience and persistence

`MathAnswerField` is a client-only Nuxt component. It loads MathLive and the Compute Engine on the client, configures numeric, symbols, and alphabetic virtual-keyboard layouts, and emits the LaTeX plus MathJSON contract only when the MathLive expression is valid.

The current assignment page switches from textarea to `MathAnswerField` only when the input descriptor declares `mathjson-v1`; all other question types keep their current textarea path. Existing Dexie drafts and outbox rows carry the structured answer without a schema migration. A locally incomplete formula remains a local draft with inline feedback and is not put in the sync queue until valid.

## Testing

Tests are written before implementation and cover:

- M2@2 policy validation, version isolation, and student detail redaction;
- MathJSON validation, conversion, all structural limits, safe symbol checks, zero denominator handling, and `expanded` detection;
- numerical exactness and tolerance, expression equivalence, form partial credit, and `needs_review` outcomes;
- worker timeout and resource-limit mapping without a raw 500 response;
- MathLive payload construction and virtual-keyboard configuration through a browser-independent adapter test;
- student save normalization and preservation of server-owned AST;
- a parameterized golden fixture with at least 100 correct, partial, incorrect, boundary, invalid, and adversarial cases.

Published question versions continue to require a passing version-bound test run. M2@2 adds `invalid_mathjson` and `resource_limit` to its required categories so unsafe behavior is verified before publication.

## Acceptance mapping

MathLive and mobile keyboard satisfy student input; the answer contract retains display and structure; the server-owned dialect and AST enforce the whitelist and hard limits; the child process plus Compose limits provide configurable isolation; bounded numeric and algebraic graders cover automatic outcomes and form checks; explicit domain restrictions prevent false claims; structured review results handle errors; and the golden fixture supplies the required broad regression coverage.
