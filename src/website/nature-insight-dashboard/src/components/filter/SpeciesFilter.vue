<template>
  <div :class="['filter-panel', theme]">

    <div class="panel-title">
      CONTROL PANEL
    </div>


    <div class="group">

      <div class="group-title">
        🧬 Species
      </div>


      <!-- Kingdom -->
      <div class="item">

        <label>
          Kingdom
        </label>

        <select
          v-model="filters.kingdom"
          @change="onKingdomChange"
        >

          <option
            v-for="k in kingdoms"
            :key="k"
            :value="k"
          >
            {{ k }}
          </option>

        </select>

      </div>



      <!-- Category -->
      <div class="item">

        <label>
          Category
        </label>


        <select
          v-model="filters.category"
          @change="onCategoryChange"
        >

          <option
            v-for="c in categories"
            :key="c"
            :value="c"
          >
            {{ c }}
          </option>


        </select>

      </div>



      <!-- Genus -->
      <div class="item">

        <label>
          Genus
        </label>


        <select
          v-model="filters.genus"
        >

          <option
            v-for="g in genera"
            :key="g"
            :value="g"
          >
            {{ g }}
          </option>


        </select>


      </div>


    </div>


  </div>
</template>


<script setup>

import {
  ref,
  computed,
  inject,
  onMounted
} from 'vue'

import { speciesFilter } from '@/stores/speciesFilter'


const theme = inject('theme')


/*
========================
store
========================
*/

const filters = speciesFilter



/*
========================
backend options
========================
*/


const options = ref({

  kingdoms: [],

  categories: {},

  genera: {}

})



const loadOptions = async()=>{


  try{


    const res = await fetch(
      '/api/species/filter-options'
    )


    options.value = await res.json()



    /*
    Initialize default values
    Do not allow All
    */


    filters.kingdom =
      options.value.kingdoms[0]



    filters.category =
      options.value.categories[
        filters.kingdom
      ][0]



    filters.genus =
      options.value.genera[
        filters.category
      ][0]


  }
  catch(err){

    console.error(
      "load filter options failed",
      err
    )

  }


}




/*
========================
computed
========================
*/


// kingdom list

const kingdoms = computed(()=>{

  return options.value.kingdoms

})




// categories for the current kingdom

const categories = computed(()=>{


  if(!filters.kingdom)
    return []


  return (
    options.value.categories[
      filters.kingdom
    ] || []
  )

})





// genera for the current category

const genera = computed(()=>{


  if(!filters.category)
    return []


  return (
    options.value.genera[
      filters.category
    ] || []
  )

})





/*
========================
cascade
========================
*/


const onKingdomChange = ()=>{


  filters.category =
    categories.value[0]


  filters.genus =
    genera.value[0]


}




const onCategoryChange = ()=>{


  filters.genus =
    genera.value[0]


}





onMounted(()=>{

  loadOptions()

})



</script>





<style scoped>


.filter-panel{

    position: sticky;

    top:152px;

    align-self:start;

    z-index:20;

    padding:16px;

    border-radius:14px;

    backdrop-filter:blur(16px);

    transition:all .25s ease;

}




.filter-panel.light {

  background:
  rgba(255,255,255,0.92);


  border:
  1px solid rgba(59,130,246,0.15);


  box-shadow:
  0 0 0 1px rgba(59,130,246,0.05),
  0 10px 30px rgba(0,0,0,0.06);

}




.filter-panel.dark {


  background:
  rgba(17,24,39,0.82);


  border:
  1px solid rgba(59,130,246,0.18);


  box-shadow:

  0 0 20px rgba(59,130,246,0.08),
  0 10px 35px rgba(0,0,0,0.35);


  color:#E5E7EB;

}





.panel-title{


  font-size:12px;

  letter-spacing:2px;

  font-weight:600;

  opacity:.7;

  margin-bottom:14px;


}





.group{

  margin-bottom:18px;

}





.group-title{


  font-size:13px;

  font-weight:600;

  margin-bottom:10px;

  color:#3B82F6;


}





.item{


  display:flex;

  flex-direction:column;

  margin-bottom:12px;


}





.item label{


  font-size:12px;

  margin-bottom:6px;

  opacity:.75;


}





select{


  width:100%;

  padding:8px 10px;


  border-radius:10px;


  font-size:13px;


  cursor:pointer;


  outline:none;



  background:
  rgba(255,255,255,.75);


  border:
  1px solid rgba(148,163,184,.5);


}





select:hover{

border-color:
rgba(59,130,246,.5);

}





.filter-panel.dark select{


background:
rgba(31,41,55,.8);


border:
1px solid rgba(59,130,246,.25);


color:#E5E7EB;


}




.filter-panel:hover{


transform:
translateY(-2px);



box-shadow:

0 0 20px rgba(59,130,246,.12),

0 15px 40px rgba(0,0,0,.15);


}


</style>
