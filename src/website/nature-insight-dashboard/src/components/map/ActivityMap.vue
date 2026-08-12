<template>
  <div :class="['map-wrapper', theme]">

    <div class="chart-title">
      🌍 Activity Distribution Map
    </div>


    <div ref="mapRef" class="map"></div>


    <!-- legend -->
    <div :class="['legend', theme]">

      <div class="legend-header">
        <span>Activity Count</span>
        <span class="legend-dot"></span>
      </div>


      <div class="gradient"></div>


      <div class="legend-label">
        <span>Low</span>
        <span>High</span>
      </div>


      <div class="legend-value">
        <span>0</span>
        <span>{{ maxValue }}</span>
      </div>


    </div>


  </div>
</template>



<script setup>

import {
  ref,
  computed,
  inject,
  onMounted,
  onUnmounted,
  watch
} from 'vue'


import * as echarts from 'echarts'


import chinaJson from '../../assets/geojson/china.json'
console.log(
  chinaJson.features.map(
    f=>({
      name:f.properties?.name,
      type:f.geometry.type
    })
  )
)


import { toMapData } from '@/utils/provinceMap'


import { activityFilter } from '@/stores/activityFilter'



const theme = inject('theme')

const mapRef = ref(null)


let chart = null

let registered = false


const currentMapData = ref([])



/*
========================
API
========================
*/


const loadActivityMap = async(activity)=>{


  if(!activity)
    return []


  try{


    const res = await fetch(
      `/api/activity/map?activity=${encodeURIComponent(activity)}`
    )


    const data = await res.json()


    return data


  }
  catch(err){


    console.error(
      "load activity map failed",
      err
    )


    return []


  }


}




/*
========================
max value
========================
*/


const maxValue = computed(()=>{


  if(
    currentMapData.value.length===0
  )
    return 0



  return Math.max(
    ...currentMapData.value.map(
      d=>d.value
    )
  )


})




/*
========================
init map
========================
*/


const ensureMap=()=>{


  if(!registered){


    echarts.registerMap(
      'china',
      chinaJson
    )


    registered=true


  }


}





const initChart=()=>{


  if(!chart){


    chart=echarts.init(
      mapRef.value
    )


  }


}





/*
========================
render
========================
*/


const renderMap = async(activity)=>{


  if(!mapRef.value)
    return



  initChart()

  ensureMap()



  const rawData =
    await loadActivityMap(activity)



  currentMapData.value = rawData.map(d=>({

    name:d.province_zh,

    en:d.province_en,

    value:d.value

}))

  console.log(
    currentMapData.value.filter(
        d =>
        d.name==="Taiwan Province" ||
        d.name==="South China Sea Islands"
    )
)


  const isDark =
    theme.value === 'dark'




  const option = {

  backgroundColor:'transparent',


  tooltip: {

    trigger:'item',

    formatter(params){


        const item = params.data || {}


        return `

        <div style="
        font-size:14px;
        font-weight:600;
        ">

        ${item.en}

        </div>


        <div style="margin-top:6px">

        Activity Count:

        <b>
        ${params.value || 0}
        </b>

        </div>

        `

    }

},


  /*
  ==========================
  🔥 Key change
  ==========================
  */
  visualMap:{

    min:0,

    max:maxValue.value || 1,

    show:false,

    calculable:false,


    inRange:{

      color:[
        '#E8F1FF',
        '#93C5FD',
        '#3B82F6',
        '#1D4ED8'
      ]

    }

  },


  series:[{


    type:'map',

    map:'china',

    roam:true,

    zoom:1.2,

    center:[104,29],



    label:{

      show:false

    },



    itemStyle:{


      areaColor:
        isDark
        ?
        '#111827'
        :
        '#F8FAFC',



      borderColor:
        isDark
        ?
        '#475569'
        :
        '#94A3B8',


      borderWidth:1.2

    },



    emphasis:{


      label:{

        show:true,

        color:'#FFFFFF'

      },


      itemStyle:{


        areaColor:
          isDark
          ?
          '#2563EB'
          :
          '#60A5FA'


      }

    },


    data:currentMapData.value

  }]

}



  chart.clear()


  chart.setOption(
    option,
    true
  )


  chart.resize()


}






/*
========================
lifecycle
========================
*/


const resizeHandler=()=>{

  chart?.resize()

}





onMounted(()=>{


  renderMap(
    activityFilter.activity
  )


  window.addEventListener(
    'resize',
    resizeHandler
  )


})





onUnmounted(()=>{


  window.removeEventListener(
    'resize',
    resizeHandler
  )


  chart?.dispose()


  chart=null


})





/*
========================
watch
========================
*/


watch(

()=>activityFilter.activity,

(activity)=>{


  if(activity){

    renderMap(activity)

  }


}



)



watch(

theme,

()=>{


  renderMap(
    activityFilter.activity
  )


}


)


</script>





<style scoped>

.map-wrapper{

position:relative;

background:transparent;

}



.map{

width:100%;

height:680px;

border-radius:14px;

overflow:hidden;

}




.chart-title{

position:absolute;

top:12px;

left:16px;

font-size:14px;

font-weight:600;

z-index:5;

}



.map-wrapper.light .chart-title{

color:#1f2937;

}



.map-wrapper.dark .chart-title{

color:#E5E7EB;

text-shadow:
0 0 10px rgba(59,130,246,.25);

}





/* legend */

.legend{

position:absolute;

left:25px;

bottom:25px;

width:190px;

padding:15px;

border-radius:14px;

backdrop-filter:blur(15px);

z-index:10;

transition:.25s;

}



.legend.light{

background:
rgba(255,255,255,.92);

border:
1px solid #E5E7EB;

}



.legend.dark{

background:
rgba(17,24,39,.82);

border:
1px solid rgba(255,255,255,.08);

color:#E5E7EB;

}





.legend-header{

display:flex;

justify-content:space-between;

align-items:center;

margin-bottom:12px;

font-weight:600;

}




.legend-dot{

width:10px;

height:10px;

border-radius:50%;

background:#3B82F6;

animation:pulse 2.5s infinite;

}




@keyframes pulse{

50%{

box-shadow:
0 0 16px rgba(59,130,246,.8);

}

}




.gradient{

height:10px;

border-radius:8px;

background:
linear-gradient(
90deg,
#E0ECFF,
#60A5FA,
#1D4ED8
);

}



.legend.dark .gradient{

background:
linear-gradient(
90deg,
#0F172A,
#2563EB,
#38BDF8
);

}





.legend-label,
.legend-value{

display:flex;

justify-content:space-between;

margin-top:8px;

font-size:12px;

}

</style>
