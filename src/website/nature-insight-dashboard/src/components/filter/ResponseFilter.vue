<template>

  <div :class="['filter-panel', theme]">


    <div class="panel-title">
      CONTROL PANEL
    </div>



    <div class="group">


      <div class="group-title">
        💬 Human Response
      </div>



      <div class="item">


        <label>
          Emotion
        </label>



        <select
          v-model="filters.response"
        >


          <option
            v-for="r in responseOptions"
            :key="r"
            :value="r"
          >

            {{ r }}

          </option>


        </select>



      </div>


    </div>


  </div>


</template>




<script setup>

import {
  inject,
  ref,
  onMounted
} from 'vue'


import {
  responseFilter
} from '@/stores/responseFilter'



const theme = inject('theme')


const filters = responseFilter



/*
========================
response options
========================
*/


const responseOptions = ref([])



/*
========================
load emotion top15
========================
*/


const loadResponses = async()=>{


  try{


    const res = await fetch(
      "/api/emotion/top15"
    )


    const data = await res.json()



    responseOptions.value =
      data.map(
        d=>d.emotion
      )



    // Set the default to the first emotion

    if(responseOptions.value.length > 0){

      filters.response =
        responseOptions.value[0]

    }



  }
  catch(err){

    console.error(
      "load emotion options failed",
      err
    )

  }


}




/*
========================
lifecycle
========================
*/


onMounted(()=>{


  loadResponses()


})



</script>





<style scoped>


/* =========================
   PANEL BASE
========================= */


.filter-panel{


    position:sticky;


    top:152px;


    align-self:start;


    z-index:20;


    padding:16px;


    border-radius:14px;


    backdrop-filter:blur(16px);


    transition:all .25s ease;


}





/* =========================
   LIGHT MODE
========================= */


.filter-panel.light {


  background:
  rgba(255,255,255,0.92);



  border:
  1px solid rgba(59,130,246,0.15);



  box-shadow:

  0 0 0 1px rgba(59,130,246,0.05),

  0 10px 30px rgba(0,0,0,0.06);



}





/* =========================
   DARK MODE
========================= */


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






/* =========================
TITLE
========================= */


.panel-title{


  font-size:12px;


  letter-spacing:2px;


  font-weight:600;


  opacity:.7;


  margin-bottom:14px;



}








/* =========================
GROUP
========================= */


.group{


  margin-bottom:18px;


}








.group-title{


  font-size:13px;


  font-weight:600;


  margin-bottom:10px;


  color:#3B82F6;



}








/* =========================
ITEM
========================= */


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









/* =========================
SELECT
========================= */


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



  transition:all .2s ease;



}








select:hover{


border-color:

rgba(59,130,246,.5);


}








select:focus{


border-color:#3B82F6;



box-shadow:

0 0 0 3px rgba(59,130,246,.15);



}








/* dark select */


.filter-panel.dark select{


background:

rgba(31,41,55,.8);



border:

1px solid rgba(59,130,246,.25);



color:#E5E7EB;



}








/* =========================
HOVER
========================= */


.filter-panel:hover{


transform:

translateY(-2px);



box-shadow:


0 0 20px rgba(59,130,246,.12),


0 15px 40px rgba(0,0,0,.15);



}



</style>
