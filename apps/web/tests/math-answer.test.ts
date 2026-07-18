import { describe, expect, it } from 'vitest'

import { toMathAnswer } from '../app/lib/math-answer'

describe('MathLive answer payloads', () => {
  it('keeps LaTeX and parses MathJSON', () => {
    expect(toMathAnswer({
      value: '\\frac{1}{2}',
      getValue: () => '["Rational",1,2]'
    })).toEqual({
      format: 'mathjson-v1',
      latex: '\\frac{1}{2}',
      mathjson: ['Rational', 1, 2]
    })
  })

  it('does not queue malformed or incomplete expressions', () => {
    expect(toMathAnswer({ value: 'x+', getValue: () => 'not-json' })).toBeNull()
    expect(toMathAnswer({ value: '   ', getValue: () => '[]' })).toBeNull()
  })
})
