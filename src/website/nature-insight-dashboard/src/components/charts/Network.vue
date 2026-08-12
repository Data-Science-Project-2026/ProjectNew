<template>

<div 
  class="network-card"
  :class="theme"
>


<div class="chart-title">
🕸️ Co-occurrence Network
</div>


<!-- no data -->
<div 
  v-if="noData"
  class="no-data"
>


<div class="icon">
🕸️
</div>


<div class="title">
No Network Data
</div>


<div class="desc">
No co-occurrence information available
for <b>{{currentGenus}}</b>
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
onUnmounted
}
from 'vue'


import * as echarts from 'echarts'

import {
speciesFilter
}
from '@/stores/speciesFilter'


const theme = inject('theme')


const chartRef = ref(null)

let chart=null


const nodes = ref([])

const links = ref([])

const noData = ref(false)


const currentGenus = ref('')





/*
Colors
*/
const getColor=(type,isDark)=>{


if(type==="emotion"){

return isDark
?'#FBBF24'
:'#F59E0B'

}


return isDark
?'#60A5FA'
:'#2563EB'


}





/*
Request backend
*/
const loadNetwork=async(genus)=>{


if(!genus){
return
}


currentGenus.value=genus


try{


const res=await fetch(
      `/api/species/network?genus=${encodeURIComponent(genus)}`
)


const data=await res.json()



nodes.value=data.nodes || []

links.value=data.links || []



if(
nodes.value.length===0 ||
links.value.length===0
){

noData.value=true


if(chart){

chart.dispose()
chart=null

}


return

}


noData.value=false


await nextTick()

render()


}catch(e){


console.error(
"network load failed",
e
)


noData.value=true


}


}







/*
Drawing
*/
const render=()=>{


if(!chartRef.value)
return



if(!chart){

chart=echarts.init(chartRef.value)

}



const isDark=theme.value==="dark"



chart.clear()



chart.setOption({


backgroundColor:"transparent",



tooltip:{


formatter(params){


if(params.dataType==="node"){


return `

<div>

<b>${params.name}</b>

<br/>

Type:
${params.data.type || 'species'}

<br/>

Weight:
${params.data.weight ?? 0}

</div>

`

}


if(params.dataType==="edge"){

return `

${params.data.source}
→
${params.data.target}

<br/>

Weight:
${params.data.weight}

`

}


}

},





series:[{


type:"graph",

layout:"force",

roam:true,

draggable:true,


force:{


repulsion:320,

edgeLength:140,

gravity:0.08

},



label:{


show:true,

position:"bottom",

color:isDark
?'#E5E7EB'
:'#1F2937',


fontSize:12


},



data:nodes.value.map(n=>({


name:n.id,


id:n.id,


type:n.type,


weight:n.weight,



symbolSize:

Math.max(
18,
n.weight * 45
),



itemStyle:{


color:getColor(
n.type,
isDark
),


borderColor:isDark
?'#111827'
:'#fff',


borderWidth:2,


shadowBlur:
isDark?15:8,


shadowColor:
getColor(n.type,isDark)


}



})),





links:links.value.map(l=>({


source:l.source,

target:l.target,

weight:l.weight,


lineStyle:{


color:isDark
?'rgba(148,163,184,.35)'
:'rgba(37,99,235,.35)',


width:
Math.max(
1,
l.weight*5
)


}


}))



}]



})



chart.resize()


}







onMounted(()=>{


if(speciesFilter.genus){

loadNetwork(
speciesFilter.genus
)

}



window.addEventListener(
'resize',
()=>chart?.resize()
)


})






watch(
()=>speciesFilter.genus,

(genus)=>{


loadNetwork(genus)


}

)






watch(
theme,

()=>{


if(chart){

chart.dispose()

chart=null


}


if(!noData.value){

nextTick(render)

}


}

)




onUnmounted(()=>{


chart?.dispose()

chart=null


})



</script>





<style scoped>


.network-card{


position:relative;

width:100%;

height:560px;

border-radius:14px;

overflow:hidden;

background:transparent;


}



.chart{

width:100%;

height:560px;

}



.chart-title{


position:absolute;

top:15px;

left:18px;

font-size:14px;

font-weight:600;

z-index:5;


}



/* light */

.network-card.light .chart-title{


color:#1F2937;


}



/* dark */

.network-card.dark .chart-title{


color:#E5E7EB;


}





.no-data{


height:100%;

display:flex;

flex-direction:column;

justify-content:center;

align-items:center;

text-align:center;


}




.icon{


font-size:48px;

margin-bottom:15px;

opacity:.8;


}




.title{


font-size:20px;

font-weight:700;

margin-bottom:10px;


}



.desc{


font-size:14px;

max-width:280px;

line-height:1.6;

opacity:.7;


}




.network-card.light .no-data{


color:#475569;


}




.network-card.dark .no-data{


color:#CBD5E1;


}




</style>
