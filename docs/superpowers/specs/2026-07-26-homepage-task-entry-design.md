# Homepage Task-Entry Design

## Scope

Refine the public homepage into a clear entry point for the existing student
and teacher workspaces. The page remains publicly accessible and keeps the
current authentication and role-routing behaviour.

## Goals

- Make the intended next action clear for each user role.
- Describe the immediate benefit of each role entry before asking the user to
  sign in.
- Retain a concise explanation of the platform's grading safeguards.
- Remove development-facing API information from the public interface.
- Improve keyboard focus visibility on homepage links and buttons.

## Experience

The page leads with the heading "开始你的作业与教学工作" and a short
description of the learning and review loop. Two equal task-entry cards sit
directly below it:

- Student entry: explains that students can view pending work, submit answers,
  and return for corrections. Its action leads to `/student`.
- Teacher entry: explains that teachers can create assignments, review results,
  and respond to requests. Its action leads to `/teacher`.

The existing role middleware remains responsible for redirecting unauthenticated
users to sign-in and for enforcing role access. The homepage does not request
session data or expose an administrator entry.

A secondary "为什么值得信赖" section keeps three short, user-readable
assurances: consistent grading, teacher review, and traceable feedback. This
replaces implementation terminology as the dominant content below the role
actions.

The footer is a small product-status statement and no longer renders the Core
API base URL.

## Visual And Accessibility Details

Use the existing blue, neutral background, white-card, rounded-corner visual
system. The two role entries use a responsive two-column grid that becomes one
column on narrow screens. Both calls to action remain at least 44px high.

Homepage interactive links and buttons receive a visible `:focus-visible`
outline that meets the existing workbench convention. The content continues to
use semantic sections, articles, and headings; no icon-only controls are added.

## Non-goals

- Changing authentication, session fetching, permissions, or redirects.
- Adding APIs, account switching, or personal progress data to the homepage.
- Changing student, teacher, or administrator workspace flows.

## Verification

- Add a homepage rendering test that verifies both role actions, supporting
  role descriptions, and the absence of the API URL.
- Run the focused test and the full web test suite.
- Run the Nuxt production build.
- Inspect desktop and narrow viewport renders when dependencies are available.
