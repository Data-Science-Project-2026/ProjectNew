<template>
  <div :class="['filter-panel', theme]">

    <div class="panel-title">CONTROL PANEL</div>

    <!-- 🧭 Activity -->
    <div class="group">
      <div class="group-title">🧭 Activities</div>

      <div class="item">
        <label>Activity</label>
        <select v-model="filters.activity">

          <option
          v-for="a in activityOptions"
          :key="a"
          :value="a"
          >
          {{a}}
          </option>

        </select>
      </div>

    </div>

  </div>
</template>

<script setup>

import {
    ref,
    inject,
    onMounted
} from 'vue'

import {
    activityFilter
} from '@/stores/activityFilter'


const theme = inject('theme')


const filters = activityFilter


const activityOptions = ref([])



const loadActivities = async()=>{

    try{

        const res = await fetch(
      '/api/activity/filter-options'
        )

        const data = await res.json()


        activityOptions.value = data.activities


        // Initialize the default activity
        if(activityOptions.value.length > 0){

            filters.activity =
                activityOptions.value[0]

        }


    }catch(err){

        console.error(
            "load activity failed",
            err
        )

    }

}



onMounted(()=>{

    loadActivities()

})


</script>

<style scoped>
/* =========================
   PANEL BASE (same as species)
========================= */
.filter-panel {
  position: sticky;
  top: 152px;
  align-self: start;
  z-index: 20;

  padding: 16px;
  border-radius: 14px;
  backdrop-filter: blur(16px);

  transition: all .25s ease;
}

/* LIGHT */
.filter-panel.light {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(59, 130, 246, 0.15);
  box-shadow:
    0 0 0 1px rgba(59, 130, 246, 0.05),
    0 10px 30px rgba(0, 0, 0, 0.06);
}

/* DARK */
.filter-panel.dark {
  background: rgba(17, 24, 39, 0.82);
  border: 1px solid rgba(59, 130, 246, 0.18);
  box-shadow:
    0 0 20px rgba(59, 130, 246, 0.08),
    0 10px 35px rgba(0, 0, 0, 0.35);
  color: #E5E7EB;
}

/* TITLE */
.panel-title {
  font-size: 12px;
  letter-spacing: 2px;
  font-weight: 600;
  opacity: 0.7;
  margin-bottom: 14px;
}

/* GROUP */
.group {
  margin-bottom: 18px;
}

.group-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
  color: #3B82F6;
}

/* ITEM */
.item {
  display: flex;
  flex-direction: column;
  margin-bottom: 12px;
}

.item label {
  font-size: 12px;
  margin-bottom: 6px;
  opacity: 0.75;
}

/* SELECT */
select {
  width: 100%;
  padding: 8px 10px;
  border-radius: 10px;
  font-size: 13px;

  outline: none;
  cursor: pointer;

  appearance:auto;


  background: rgba(255, 255, 255, 0.75);
  border: 1px solid rgba(148, 163, 184, 0.5);

  transition: all 0.2s ease;
}

/* hover */
select:hover {
  border-color: rgba(59, 130, 246, 0.5);
}

/* focus */
select:focus {
  border-color: #3B82F6;
  box-shadow: 0 0 0 3px rgba(59,130,246,0.15);
}

/* dark select */
.filter-panel.dark select {
  background: rgba(31, 41, 55, 0.6);
  border: 1px solid rgba(59, 130, 246, 0.2);
  color: #E5E7EB;
}

/* hover card */
.filter-panel:hover {
  transform: translateY(-2px);
  box-shadow:
    0 0 20px rgba(59, 130, 246, 0.12),
    0 15px 40px rgba(0, 0, 0, 0.15);
}
</style>
