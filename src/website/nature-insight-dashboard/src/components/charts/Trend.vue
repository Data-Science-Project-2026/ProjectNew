<template>
  <div class="trend-card" :class="theme">

    <div class="chart-title">
      📈 Species Trend
    </div>


    <!-- Year -->
    <div class="toolbar">

      <label>
        Year
      </label>


      <select
        v-model="selectedYear"
        :disabled="years.length===0"
      >

        <option
          v-for="y in years"
          :key="y"
          :value="y"
        >
          {{ y }}
        </option>


      </select>


    </div>



    <!-- no data -->
    <div
      v-if="noData"
      class="no-data"
    >

      <div class="no-icon">
        📊
      </div>


      <div class="no-title">
        No Trend Data
      </div>


      <div class="no-desc">

        No observation found for
        <b>{{ speciesFilter.genus }}</b>

        in
        <b>{{ selectedYear }}</b>

      </div>


    </div>



    <div
      v-else
      ref="chartRef"
      class="chart"
    ></div>


  </div>
</template>



<script setup>

import {
  ref,
  onMounted,
  watch,
  inject,
  nextTick
} from 'vue'


import * as echarts from 'echarts'


import { speciesFilter } from '@/stores/speciesFilter'



/* ======================
    theme
====================== */

const theme = inject('theme')



/* ======================
    chart
====================== */

const chartRef = ref(null)

let chart = null



/************************
 * year
 ************************/

const years = ref([])


const selectedYear = ref(null)



/************************
 * trend data
 ************************/

const trendData = ref([])
const noData = ref(false)


/************************
 * Get years for the selected genus
 ************************/

const loadYears = async()=>{


  if(!speciesFilter.genus)
    return


  // Clear old data
  years.value = []

  selectedYear.value = null



  try{


    const res = await fetch(

      `/api/species/years?genus=${encodeURIComponent(speciesFilter.genus)}`

    )


    const data = await res.json()



    years.value = data



    // Default to the latest year

    if(data.length>0){

      selectedYear.value =
        data[data.length-1]

    }


  }
  catch(err){

    console.error(
      "load years failed",
      err
    )

  }

}




/************************
 * Fetch trend data
 ************************/

const loadTrend = async()=>{


  if(
    !speciesFilter.genus ||
    !selectedYear.value
  )
  {
    trendData.value=[]
    return
  }



  try{


    const res = await fetch(

      `/api/species/trend?genus=${encodeURIComponent(speciesFilter.genus)}&year=${encodeURIComponent(selectedYear.value)}`

    )



    const data = await res.json()



    trendData.value=data


    noData.value =
        data.length===0


    if(noData.value){

        chart?.clear()

        return

    }


  }
  catch(err){

    console.error(
      "load trend failed",
      err
    )

  }

}




/************************
 * render echarts
 ************************/

const render = async()=>{


  await nextTick()



  if(!chartRef.value)
    return



  if(!chart){

    chart =
      echarts.init(chartRef.value)

  }



  const isDark =
    theme.value==="dark"



  const data =
    trendData.value.map(d=>({

      m:d.month,

      v:d.value

    }))



  chart.setOption({

    backgroundColor:
      'transparent',



    tooltip:{


    trigger:'axis',


    formatter(params){


    const p=params[0]


    return `

    <div style="font-weight:600">

    Month: ${p.axisValue}

    </div>


    <div>

    Observation:

    <b>${p.value}</b>

    </div>

    `

    }


    },



    grid:{

      left:35,

      right:20,

      top:20,

      bottom:30

    },



    xAxis:{


      type:'category',


      data:
        data.map(
          d=>`${d.m}`
        ),


      axisLabel:{
        color:
          isDark
          ?
          '#CBD5E1'
          :
          '#334155'
      }


    },



    yAxis:{


    type:"value",





    splitLine:{


    lineStyle:{


    color:

    isDark

    ?

    "rgba(148,163,184,.15)"

    :

    "rgba(226,232,240,.8)"


    }


    },






    axisLabel:{


    color:

    isDark

    ?

    "#CBD5E1"

    :

    "#334155"


    }



    },




    series:[

      {


        name:
          speciesFilter.genus,


        type:'line',


        smooth:true,


        data:
          data.map(
            d=>d.v
          ),


        lineStyle:{

          width:3,


          color:
            isDark
            ?
            '#60A5FA'
            :
            '#2563EB'

        },


        areaStyle:{

          color:
            isDark
            ?
            'rgba(96,165,250,0.15)'
            :
            'rgba(37,99,235,0.12)'

        },


        symbol:'circle',

        symbolSize:6

      }

    ]


  })


  chart.resize()


}





/************************
 * watch
 ************************/


// genus changes

watch(

  ()=>speciesFilter.genus,

  async()=>{


    await loadYears()


    await loadTrend()


    render()


  }

)



// year changes

watch(

  selectedYear,

  async()=>{


    await loadTrend()


    render()


  }

)



// theme changes

watch(

  theme,

  async()=>{


    await nextTick()


    chart?.dispose()


    chart=null


    render()


  }

)





/************************
 * lifecycle
 ************************/


onMounted(

async()=>{


  await loadYears()


  await loadTrend()


  render()



  window.addEventListener(
    'resize',
    ()=>{
      chart?.resize()
    }
  )


}

)


</script>





<style scoped>


.trend-card{

position:relative;

width:100%;

height:450px;

}



.chart-title{

position:absolute;

top:12px;

left:16px;

font-size:14px;

font-weight:600;

z-index:10;

}



.trend-card.light .chart-title{

color:#1f2937;

}



.trend-card.dark .chart-title{

color:#e5e7eb;

}




.toolbar{

display:flex;

align-items:center;

gap:8px;

padding-top:38px;

padding-left:16px;

}



.toolbar label{

font-size:12px;

}



select{

padding:5px 12px;

border-radius:8px;

}



.trend-card.dark select{

background:#1f2937;

color:#e5e7eb;

border:1px solid #374151;

}



.chart{

width:100%;

height:450px;

}




/***************
 no data
****************/


.no-data{

height:300px;

display:flex;

flex-direction:column;

justify-content:center;

align-items:center;

text-align:center;

}



.no-icon{

font-size:36px;

margin-bottom:10px;

}



.no-title{

font-size:16px;

font-weight:600;

}



.no-desc{

margin-top:8px;

font-size:13px;

opacity:.65;

}



.trend-card.dark .no-data{

color:#E5E7EB;

}



.trend-card.light .no-data{

color:#334155;

}



</style>
