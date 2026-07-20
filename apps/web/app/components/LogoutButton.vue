<template>
  <button class="button secondary" type="button" @click="signOut">退出登录</button>
</template>

<script setup lang="ts">
import { logout } from '../lib/auth-client'

async function signOut() {
  await logout($fetch)
  return navigateTo('/')
}
</script>
