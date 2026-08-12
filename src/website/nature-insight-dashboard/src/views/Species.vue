<template>
  <div class="layout">

    <div class="left">
      <SpeciesFilter />
    </div>

    <div class="right">

      <div class="card map">
        <ChinaMap />
      </div>

      <div class="grid">
        <div class="card">
            <Trend />
        </div>
        <div class="card">
            <Network />
        </div>
      </div>

    </div>

  </div>
</template>

<script setup>
import SpeciesFilter from '../components/filter/SpeciesFilter.vue'
import ChinaMap from '../components/map/ChinaMap.vue'
import Trend from '../components/charts/Trend.vue'
import Network from '../components/charts/Network.vue'
</script>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 16px;
}

.right {

  display:flex;

  flex-direction:column;

  gap:16px;

}

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
.dark .card {
  border: 1px solid rgba(59, 130, 246, 0.25);

  box-shadow:
    0 0 0 1px rgba(59, 130, 246, 0.2),
    0 0 25px rgba(59, 130, 246, 0.15),
    0 10px 35px rgba(0, 0, 0, 0.4);
}
.light .card {
  border: 1px solid rgba(203, 213, 225, 0.8);

  box-shadow:
    0 0 0 1px rgba(59, 130, 246, 0.05),
    0 6px 20px rgba(0, 0, 0, 0.04);
}
.card:hover {
  transform: translateY(-2px);

  box-shadow:
    0 0 0 1px rgba(59, 130, 246, 0.25),
    0 12px 40px rgba(59, 130, 246, 0.15);
}
.map {
  min-height: 520px;
}

.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
</style>