# Teacher Workbench Layout Design

## Scope

Rework the teacher-facing Nuxt page into a responsive, module-oriented
workbench. The work covers the dashboard overview and the question and
assignment creation experiences shown in the supplied reference. It does not
change API contracts, persistence models, authorisation, or grading rules.

## Goals

- Make the teacher's next action visible without scrolling through creation
  forms.
- Separate review, question-bank, assignment, and student-request work into
  clear visual modules.
- Give question and assignment creation forms consistent labels, controls,
  validation space, and submit actions.
- Keep all primary flows usable on narrow screens without horizontal overflow.

## Information Architecture

Desktop uses a persistent left navigation with these modules: Workbench,
Review Queue, Question Bank, Assignments, and Student Requests. The top bar
contains the teacher identity and session actions.

The Workbench is the default module. It contains three summary metrics,
priority actions for review and student requests, active-assignment context,
and entry points for the two creation modules. Navigation changes the active
module in the client without changing backend contracts. On small screens, the
left navigation becomes a compact, horizontally scrollable module bar below
the top bar.

The Question Bank module uses a two-column desktop layout: a compact list or
empty state on the left and the question creation form on the right. The
Assignments module follows the same pattern, with an assignment list or empty
state alongside the assignment creation form. Below the content breakpoint,
both modules become a single column with the list/empty state preceding the
form.

## Components and State

`teacher/index.vue` becomes the page-level coordinator. It owns the active
module and the data needed to render the existing summary and empty states.
Presentational components are split by responsibility:

- a workbench shell for top bar, navigation, and responsive content region;
- an overview panel for metrics, priority actions, and quick-start links;
- a question-bank workspace containing list/empty state and creation form;
- an assignments workspace containing list/empty state and creation form.

Form state remains local to its workspace. Field labels sit above their
controls; error text is rendered directly beneath the affected control. The
question and assignment submit handlers keep their existing integration seams
so a later API connection can call the already available question and
assignment endpoints without reshaping their requests.

## Visual System

The page uses the existing blue primary action colour, a low-contrast grey
application background, white cards, and one radius/shadow scale. The content
container expands beyond the current narrow desktop width while preserving a
comfortable reading measure. Metrics use subdued labels and strong values;
primary buttons are reserved for creating or starting work. Empty states
explain the next action and point to the corresponding creation form.

## Error Handling and Accessibility

Required input errors are visible next to the relevant field and announced by
standard semantic form controls. Buttons expose disabled or submitting states
when wiring is introduced. Navigation and form controls are reachable with the
keyboard, retain visible focus styling, and use no icon-only primary actions.
The responsive design keeps touch targets at least 44px tall.

## Verification

- Add focused component or page tests for module switching, question-form
  required fields, assignment-form required fields, and empty-state actions.
- Run the web test suite.
- Build the Nuxt app to catch template and CSS integration errors.
- Inspect desktop and narrow viewport renderings for overflow, wrapping, and
  usable primary actions.

## Non-goals

- Adding endpoints for teacher-side list, metrics, review, or request data.
- Changing the existing question, assignment, or authentication APIs.
- Implementing grading, publication, or student-request decisions.
