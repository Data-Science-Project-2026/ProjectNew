<template>
  <div class="layout">

    <div class="left">
      <ResponseFilter />
    </div>


    <div class="right">

      <div class="card map">
        <ResponseMap />
      </div>


      <div class="card trend">
        <ResponseTrend />
      </div>


    </div>

  </div>
</template>


<script setup>

import ResponseFilter from '../components/filter/ResponseFilter.vue'
import ResponseMap from '../components/map/ResponseMap.vue'
import ResponseTrend from '../components/charts/ResponseTrend.vue'

</script>


<style scoped>
.layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 16px;
}

/* shared card style */
.card {
  background: transparent;
  border-radius: 14px;
  padding: 16px;

  border: 1px solid rgba(229, 231, 235, 0.6);
  box-shadow:
    0 0 0 1px rgba(59, 130, 246, 0.08),
    0 8px 30px rgba(0, 0, 0, 0.06);

  transition: all 0.25s ease;
}

/* dark mode */
.dark .card {
  border: 1px solid rgba(59, 130, 246, 0.25);
  box-shadow:
    0 0 0 1px rgba(59, 130, 246, 0.2),
    0 0 25px rgba(59, 130, 246, 0.15),
    0 10px 35px rgba(0, 0, 0, 0.4);
}

/* light mode */
.light .card {
  border: 1px solid rgba(203, 213, 225, 0.8);
  box-shadow:
    0 0 0 1px rgba(59, 130, 246, 0.05),
    0 6px 20px rgba(0, 0, 0, 0.04);
}

.card:hover {
  transform: translateY(-2px);
}

/* layout sizing */
.map {
  min-height: 520px;
}

.trend {
  margin-top: 16px;
  height: 360px;
}
</style>