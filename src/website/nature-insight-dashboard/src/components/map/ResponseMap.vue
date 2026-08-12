<template>

<div class="map-wrapper" :class="theme">


  <div class="chart-title">
    🌍 Human Emotion Distribution Map
  </div>


  <div ref="mapRef" class="map"></div>



  <div :class="['legend',theme]">

    <div class="legend-header">

      <span>
        Emotion Count
      </span>

      <span class="legend-dot"></span>

    </div>


    <div class="gradient"></div>


    <div class="legend-label">
      <span>Low</span>
      <span>High</span>
    </div>


    <div class="legend-value">

      <span>0</span>

      <span>
        {{maxValue}}
      </span>

    </div>


  </div>



</div>

</template>




<script setup>

import {

onMounted,

onUnmounted,

ref,

inject,

watch,

computed

} from 'vue'



import * as echarts from 'echarts'



import chinaJson
from '../../assets/geojson/china.json'



import {
responseFilter
}
from '@/stores/responseFilter'





const theme = inject('theme')



const mapRef = ref(null)



let chart = null



let isRegistered = false





/*
========================
data
========================
*/


const currentData = ref([])







const maxValue = computed(()=>{


if(
currentData.value.length===0
)

return 0



return Math.max(

...currentData.value.map(
d=>d.value
),

1

)


})









/*
========================
API
========================
*/


const getMapData = async(emotion)=>{


if(!emotion)

return []




try{


const res = await fetch(

      `/api/emotion/map?emotion=${encodeURIComponent(emotion)}`

)



const data = await res.json()





/*
Do not use toMapData

Keep English names

*/


return data.map(d=>({



/*
Must match geojson

*/

name:d.province_zh,



value:d.value,



province_en:d.province_en,



province_zh:d.province_zh



}))



}



catch(err){


console.error(

"emotion map api error",

err

)



return []


}



}









/*
========================
register china
========================
*/


const ensureMap=()=>{


if(!isRegistered){


echarts.registerMap(

"china",

chinaJson

)



isRegistered=true


}


}









const initChart=()=>{


if(!mapRef.value)

return




if(!chart){


chart =
echarts.init(
mapRef.value
)


}


}









/*
========================
render
========================
*/


const renderMap = async(emotion)=>{


initChart()


ensureMap()




const isDark =
theme.value==="dark"





const rawData =
await getMapData(emotion)





currentData.value =
rawData





const option={




backgroundColor:
'transparent',






tooltip:{



trigger:"item",





backgroundColor:

isDark

?

"rgba(17,24,39,.95)"

:

"#ffffff",





borderColor:

isDark

?

"#374151"

:

"#E5E7EB",





textStyle:{



color:

isDark

?

"#E5E7EB"

:

"#111827"



},





formatter(params){



const item =
params.data



return `


<div style="
font-size:14px;
font-weight:600;
">


${

item?.province_en

||

params.name

}



</div>




<div style="
margin-top:6px;
">


Emotion Count:


<b>

${

item?.value || 0

}


</b>


</div>


`



}



},







visualMap:{


show:false,


min:0,


max:
maxValue.value || 1,



inRange:{


color:[


"#E0ECFF",


"#60A5FA",


"#1D4ED8"


]


}


},







series:[


{


type:"map",


map:"china",




zoom:1.2,



center:[104,29],




roam:true,





label:{


show:false


},







itemStyle:{



borderColor:


isDark

?

"#334155"

:

"#94A3B8",





borderWidth:1.2,





areaColor:


isDark

?

"#0F172A"

:

"#F8FAFC"



},







emphasis:{





label:{



show:true,



color:"#ffffff",



fontSize:12



},






itemStyle:{



areaColor:


isDark

?

"#2563EB"

:

"#93C5FD"



}



},







data:rawData



}


]



}






chart.clear()



chart.setOption(

option,

true

)



}









/*
========================
resize
========================
*/


const resizeHandler=()=>{


chart?.resize()


}









/*
========================
life
========================
*/


onMounted(()=>{


renderMap(

responseFilter.response

)




window.addEventListener(

"resize",

resizeHandler

)



})








onUnmounted(()=>{


window.removeEventListener(

"resize",

resizeHandler

)




chart?.dispose()



chart=null



})









/*
========================
filter
========================
*/


watch(

()=>responseFilter.response,


(val)=>{


renderMap(val)



}



)









/*
========================
theme
========================
*/


watch(

theme,


()=>{


renderMap(

responseFilter.response

)



}

)





</script>









<style scoped>


.map-wrapper{


position:relative;


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


color:#e5e7eb;


}







.legend{


position:absolute;


left:25px;


bottom:25px;


width:190px;


padding:15px;


border-radius:14px;


backdrop-filter:blur(15px);


z-index:10;


}





.legend.light{


background:

rgba(255,255,255,.92);


}





.legend.dark{


background:

rgba(17,24,39,.82);


color:#E5E7EB;


}








.legend-header{


display:flex;


justify-content:space-between;


font-weight:600;


margin-bottom:12px;


}








.legend-dot{


width:10px;


height:10px;


border-radius:50%;


background:#3B82F6;


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







.legend-label,


.legend-value{


display:flex;


justify-content:space-between;


margin-top:8px;


font-size:12px;



}



</style>
