<template>

<div 
  class="trend-card"
  :class="theme"
>


  <div class="chart-title">

    📈 Human Response Trend

  </div>



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
      <b>{{ responseFilter.response }}</b>

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

onBeforeUnmount,

watch,

inject,

nextTick

}

from 'vue'


import * as echarts from 'echarts'


import {
responseFilter
}
from '@/stores/responseFilter'





/*
========================
theme
========================
*/


const theme = inject(
  'theme',
  ref('light')
)






/*
========================
chart
========================
*/


const chartRef = ref(null)

let chart=null





/*
========================
year
========================
*/


const years = ref([])


const selectedYear = ref(null)





/*
========================
data
========================
*/


const trendData = ref([])


const noData = ref(false)






/*
========================
load years
========================
*/


const loadYears = async()=>{


const response =
responseFilter.response



if(!response){

  years.value=[]

  selectedYear.value=null

  return

}




try{


const res = await fetch(

      `/api/emotion/trend-years?response=${encodeURIComponent(response)}`

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
"load years failed",
err
)


}



}









/*
========================
load trend
========================
*/


const loadTrend = async()=>{


const response =
responseFilter.response



const year =
selectedYear.value




if(
!response ||
!year
){

return

}





try{


console.log(
"request emotion trend",
{
response,
year
}
)




const res = await fetch(


      `/api/emotion/trend?response=${encodeURIComponent(response)}&year=${encodeURIComponent(year)}`


)





const data =
await res.json()





console.log(
"emotion trend response",
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
"load trend failed",
err
)


trendData.value=[]

noData.value=true


}



}









/*
========================
render
========================
*/


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




chart.clear()





const isDark =
theme.value==="dark"





const name =

responseFilter.response==="All"

?

"All Responses"

:

responseFilter.response





chart.setOption({



backgroundColor:
"transparent",





tooltip:{


trigger:"axis",



axisPointer:{


type:"line"


},



backgroundColor:

isDark

?

"rgba(17,24,39,0.9)"

:

"#fff",





borderColor:

isDark

?

"#374151"

:

"#e5e7eb",






textStyle:{


color:

isDark

?

"#e5e7eb"

:

"#111827"


},




formatter(params){


const p=params[0]


return `


<div style="font-weight:600">

${p.axisValue}

</div>


<div>

Response Count:

<b>${p.value}</b>

</div>


`


}



},







grid:{


left:35,

right:20,

top:55,

bottom:30


},







xAxis:{


type:"category",



data:

trendData.value.map(

d=>

d.month

),




axisLabel:{


color:

isDark

?

"#CBD5E1"

:

"#334155"


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


name,


type:"line",


smooth:true,



symbol:"circle",


symbolSize:7,




data:

trendData.value.map(

d=>

d.post_num

),






lineStyle:{


width:3,


color:

isDark

?

"#60A5FA"

:

"#2563EB"



},





areaStyle:{


color:

isDark

?

"rgba(96,165,250,.15)"

:

"rgba(37,99,235,.12)"



}



}


]





})




chart.resize()



}









/*
========================
resize
========================
*/


const resizeChart = ()=>{


chart?.resize()


}









/*
========================
mounted
========================
*/


onMounted(async()=>{


await loadYears()


await loadTrend()



window.addEventListener(

"resize",

resizeChart

)



})









/*
========================
response change
========================
*/


watch(

()=>responseFilter.response,


async()=>{


await loadYears()


// 强制刷新
await loadTrend()


}


)









/*
========================
year change
========================
*/


watch(

selectedYear,


()=>{


loadTrend()


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


chart?.dispose()


chart=null



render()



}

)









/*
========================
destroy
========================
*/


onBeforeUnmount(()=>{


chart?.dispose()



window.removeEventListener(

"resize",

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
