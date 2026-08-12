<template>

<div class="map-wrapper">

  <div class="chart-title">
    🌍 Species Distribution Map
  </div>


  <div ref="mapRef" class="map"></div>



  <div :class="['legend', theme]">

    <div class="legend-header">

      <span>
        Species Count
      </span>

      <span class="legend-dot"></span>

    </div>


    <div class="gradient"></div>


    <div class="legend-label">

      <span>
        Low
      </span>

      <span>
        High
      </span>

    </div>


    <div class="legend-value">

      <span>
        0
      </span>

      <span>
        {{ maxValue }}
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

  speciesFilter

} from '@/stores/speciesFilter'





/*
========================
theme
========================
*/


const theme = inject('theme')







/*
========================
chart
========================
*/


const mapRef = ref(null)


let chart = null


let isRegistered = false






/*
========================
data
========================
*/


const currentMapData = ref([])







/*
========================
API
========================
*/


const getMapData = async(genus)=>{


  if(!genus)

    return []




  try{


    const res = await fetch(

      `/api/species/map?genus=${encodeURIComponent(genus)}`

    )



    const data = await res.json()



    /*
    Do not use toMapData

    Keep English fields

    */


    return data.map(d=>({



      /*
      ECharts matches geojson

      Must be Chinese

      */


      name:
        d.province_zh,



      value:
        d.value,



      province_en:
        d.province_en,



      province_zh:
        d.province_zh



    }))



  }

  catch(err){


    console.error(
      "load species map failed",
      err
    )



    return []


  }


}









/*
========================
max
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
    ),

    1

  )


})









/*
========================
color
========================
*/


const getAreaColor=(

  value,

  max,

  isDark

)=>{


  if(value===0){


    return isDark

      ?

      '#111827'

      :

      '#F8FAFC'


  }





  const ratio =
    value / max





  if(isDark){


    if(ratio<0.3)

      return '#1E3A8A'



    if(ratio<0.7)

      return '#2563EB'



    return '#38BDF8'


  }



  else{


    if(ratio<0.3)

      return '#DBEAFE'



    if(ratio<0.7)

      return '#60A5FA'



    return '#1D4ED8'


  }


}









/*
========================
register
========================
*/


const ensureMap=()=>{


  if(!isRegistered){



    echarts.registerMap(

      'china',

      chinaJson

    )



    isRegistered=true


  }


}









/*
========================
render
========================
*/


const renderMap = async(genus)=>{


  const raw = await getMapData(genus)



  currentMapData.value = raw






  if(!mapRef.value)

    return





  if(!chart){


    chart =
      echarts.init(
        mapRef.value
      )


  }





  ensureMap()






  const isDark =

    theme.value === 'dark'





  const max =

    maxValue.value





  const data = raw.map(d=>({



    name:d.name,


    value:d.value,


    province_en:d.province_en,


    province_zh:d.province_zh,



    itemStyle:{


      areaColor:

        getAreaColor(

          d.value,

          max,

          isDark

        )


    }


  }))







  const option={




    backgroundColor:

      isDark

      ?

      '#0B1220'

      :

      '#F5F7FA',







    tooltip:{



      trigger:'item',




      backgroundColor:

        isDark

        ?

        '#111827'

        :

        '#FFFFFF',





      borderColor:

        isDark

        ?

        '#374151'

        :

        '#E5E7EB',





      textStyle:{


        color:

          isDark

          ?

          '#E5E7EB'

          :

          '#111827'


      },






      formatter(params){



        const item =
          params.data



        return `


        <div style="
        font-size:14px;
        font-weight:600;
        margin-bottom:6px;
        ">


        ${
          item?.province_en
          ||
          params.name
        }



        </div>



        <div>

        Records:

        <b>

        ${
          item?.value || 0
        }

        </b>


        </div>


        `



      }



    },








    series:[{


      type:'map',



      map:'china',




      roam:true,




      zoom:1.2,




      center:[

        104,

        29

      ],






      label:{


        show:false


      },








      itemStyle:{



        borderColor:

          isDark

          ?

          '#475569'

          :

          '#94A3B8',




        borderWidth:1.2,




        areaColor:

          isDark

          ?

          '#111827'

          :

          '#F8FAFC',






        shadowBlur:

          isDark

          ?

          12

          :

          0,






        shadowColor:

          isDark

          ?

          'rgba(56,189,248,0.35)'

          :

          'rgba(37,99,235,0.15)'


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

            '#7DD3FC'

            :

            '#2563EB'




        }


      },








      data:data



    }]



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

    speciesFilter.genus

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

()=>speciesFilter.genus,


(genus)=>{


  renderMap(genus)


}



)







watch(

theme,


()=>{


  renderMap(

    speciesFilter.genus

  )


}


)



</script>









<style scoped>


.map{

width:100%;

height:680px;

border-radius:14px;

overflow:hidden;

}



.map-wrapper{

position:relative;

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


background:#38BDF8;


}







.gradient{


height:10px;


border-radius:8px;


background:

linear-gradient(

90deg,

#DBEAFE,

#60A5FA,

#1D4ED8

);


}







.legend.dark .gradient{


background:

linear-gradient(

90deg,

#111827,

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
