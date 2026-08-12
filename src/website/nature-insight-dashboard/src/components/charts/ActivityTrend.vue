<template>
  <div class="trend-card" :class="theme">

    <div class="chart-title">
      📈 Activity Trend
    </div>


    <!-- Year -->
    <div class="toolbar">

      <label>
        Year
      </label>


      <select
        v-model="selectedYear"
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

        No posts found for
        <b>{{ activityFilter.activity }}</b>

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
  nextTick,
  onBeforeUnmount
} from 'vue'

import * as echarts from 'echarts'

import {
  activityFilter
} from '@/stores/activityFilter'



/*************************
 * theme
 *************************/

const theme = inject(
  'theme',
  ref('light')
)



/*************************
 * chart
 *************************/

const chartRef = ref(null)

let chart = null



/*************************
 * year
 *************************/

const years = ref([])

const selectedYear = ref(null)



/*************************
 * data
 *************************/

const trendData = ref([])

const noData = ref(false)

const loading = ref(false)



/*************************
 * load years
 *************************/


const loadYears = async()=>{


  const activity =
    activityFilter.activity


  if(!activity){

    years.value=[]
    selectedYear.value=null

    return

  }



  try{


    const res = await fetch(

      `/api/activity/trend-years?activity=${encodeURIComponent(activity)}`

    )


    const data =
      await res.json()



    years.value=data



    if(data.length){


      selectedYear.value =
        data[data.length-1]


    }
    else{


      selectedYear.value=null

      trendData.value=[]

      noData.value=true


      chart?.clear()

    }



  }
  catch(err){

    console.error(
      "load years error",
      err
    )


    years.value=[]

  }


}






/*************************
 * load trend
 *************************/


const loadTrend = async()=>{


  const activity =
    activityFilter.activity


  const year =
    selectedYear.value



  if(
    !activity ||
    !year
  ){

    return

  }



  loading.value=true



  try{


    console.log(
      "request trend",
      {
        activity,
        year
      }
    )



    const res = await fetch(

      `/api/activity/trend?activity=${encodeURIComponent(activity)}&year=${encodeURIComponent(year)}`

    )



    const data =
      await res.json()



    console.log(
      "trend response",
      data
    )



    trendData.value=data



    noData.value =
      data.length===0



    if(noData.value){

      chart?.clear()

      return

    }



    render()



  }
  catch(err){

    console.error(
      "load trend error",
      err
    )


    trendData.value=[]

    noData.value=true


  }
  finally{

    loading.value=false

  }



}






/*************************
 * render chart
 *************************/


const render = async()=>{


  await nextTick()



  if(
    !chartRef.value ||
    noData.value
  ){

    return

  }



  if(!chart){


    chart =
      echarts.init(
        chartRef.value
      )


  }



  const isDark =
    theme.value==='dark'



  chart.clear()



  chart.setOption({



    tooltip:{


      trigger:'axis',


      formatter(params){


        const p=params[0]


        return `

        <div style="font-weight:600">
        ${p.axisValue}
        </div>

        <div>
        Activity Count:
        <b>${p.value}</b>
        </div>

        `


      }


    },



    grid:{


      left:40,

      right:20,

      top:55,

      bottom:35


    },



    xAxis:{


      type:'category',


      data:
      trendData.value.map(
        d=>d.month
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




    series:[{


      name:
      activityFilter.activity,


      type:'line',

      smooth:true,


      symbol:'circle',

      symbolSize:7,



      data:
      trendData.value.map(
        d=>d.post_num
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
        'rgba(96,165,250,.15)'
        :
        'rgba(37,99,235,.12)'


      }


    }]


  })



  chart.resize()



}






/*************************
 * activity change
 *************************/


watch(

()=>activityFilter.activity,


async()=>{


  await loadYears()


  // 强制刷新
  await loadTrend()


}


)






/*************************
 * year change
 *************************/


watch(

selectedYear,


()=>{


  loadTrend()


}


)






/*************************
 * mounted
 *************************/


onMounted(async()=>{


  await loadYears()


  await loadTrend()



  window.addEventListener(
    'resize',
    resizeChart
  )


})





const resizeChart = ()=>{

  chart?.resize()

}





/*************************
 * theme change
 *************************/


watch(

theme,


()=>{


  chart?.dispose()


  chart=null


  render()


}


)





/*************************
 * destroy
 *************************/


onBeforeUnmount(()=>{


  chart?.dispose()


  window.removeEventListener(
    'resize',
    resizeChart
  )


})



</script>





<style scoped>


.trend-card{

  position:relative;

  width:100%;

  height:360px;

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

  height:300px;


}





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
