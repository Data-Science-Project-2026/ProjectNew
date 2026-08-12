<template>
  <div :class="['app', theme]">
    
    <!-- Header -->
    <header class="header">
      <div class="title">🌿 Nature Insight Dashboard</div>

      <button class="theme-btn" @click="toggleTheme">
        {{ theme === 'light' ? '🌙 Dark' : '☀ Light' }}
      </button>
    </header>

    <!-- Tabs -->
    <nav class="tabs">
      <router-link to="/species">Species</router-link>
      <router-link to="/activities">Activities</router-link>
      <router-link to="/responses">Human Responses</router-link>
    </nav>

    <!-- Page Content -->
    <main class="content">
      <router-view />
    </main>

  </div>
</template>

<script setup>
import { ref, provide } from 'vue'

const theme = ref('light')

const toggleTheme = () => {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
}

provide('theme', theme)
</script>

<style scoped>
/* ========== LIGHT THEME ========== */
.app {
  min-height: 100vh;
  width: 100%;
  display: flex;
  flex-direction: column;
}

.app.light {
  background: #F5F7FA;
  color: #1F2937;
}

/* ========== DARK THEME ========== */
.app.dark {
  background: #0B1220;
  color: #E5E7EB;
}
:global(html),
:global(body),
:global(#app) {
  margin: 0;
  padding: 0;
  width: 100%;
  height: 100%;
}

/* Header */
.header {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;

  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;

  padding: 0 24px;

  z-index: 1000;

  backdrop-filter: blur(12px);
}

.app.light .header {
  background: rgba(245, 247, 250, 0.85);
  border-bottom: 1px solid #e5e7eb;
}

.app.dark .header {
  background: rgba(11, 18, 32, 0.85);
  border-bottom: 1px solid #1f2937;
}


.title {
  font-size: 18px;
  font-weight: 600;
}

/* Theme button */
.theme-btn {
  border: 1px solid #ccc;
  background: transparent;
  padding: 6px 12px;
  border-radius: 8px;
  cursor: pointer;
}

.app.dark .theme-btn {
  border-color: #374151;
  color: #E5E7EB;
}

/* Tabs */
.tabs {
  position: fixed;
  top: 64px;          /* Header height */
  left: 0;
  right: 0;

  display: flex;
  justify-content: center;
  gap: 40px;

  padding: 16px 0;

  z-index: 999;

  background: inherit;
  border-bottom: 1px solid #e5e7eb;
}

.app.light .tabs {
  background: rgba(245,247,250,0.92);
}

.app.dark .tabs {
  background: rgba(11,18,32,0.92);
  border-bottom: 1px solid #1F2937;
}

.tabs a {
  text-decoration: none;
  color: #6B7280;
  font-weight: 500;
}

.tabs a.router-link-active {
  color: #2F80ED;
  font-weight: 600;
}

/* Content */
.content {
  padding: 24px;
  padding-top: 152px;
}
</style>