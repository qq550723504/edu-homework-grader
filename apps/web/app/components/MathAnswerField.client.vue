<template>
  <div>
    <div ref="host" class="math-answer-field" />
    <p v-if="!modelValue" class="notice">请输入一个完整的数学表达式。</p>
  </div>
</template>

<script setup lang="ts">
import { toMathAnswer, type MathAnswer } from '../lib/math-answer'

const props = defineProps<{ modelValue: MathAnswer | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: MathAnswer | null] }>()
const host = ref<HTMLElement | null>(null)
let field: { value: string; getValue(format: 'math-json'): string; addEventListener(type: string, listener: () => void): void } | null = null

onMounted(async () => {
  const [{ mathVirtualKeyboard }] = await Promise.all([
    import('mathlive'),
    import('@cortex-js/compute-engine')
  ])
  mathVirtualKeyboard.layouts = ['numeric', 'symbols', 'alphabetic']
  const element = document.createElement('math-field') as unknown as typeof field
  if (!element || !host.value) return
  field = element
  field.value = props.modelValue?.latex ?? ''
  ;(element as unknown as { mathVirtualKeyboardPolicy: string }).mathVirtualKeyboardPolicy = 'auto'
  element.addEventListener('input', () => emit('update:modelValue', toMathAnswer(element)))
  host.value.append(element as unknown as Node)
})

watch(() => props.modelValue?.latex, (latex) => {
  if (field && field.value !== (latex ?? '')) field.value = latex ?? ''
})
</script>

<style scoped>
.math-answer-field :deep(math-field) { width: 100%; min-height: 3rem; padding: .7rem; border: 1px solid #b9c7dc; border-radius: .5rem; font-size: 1.2rem; }
</style>
