export const provinceMap = [
  { en: 'Guangdong', cn: '广东省' },
  { en: 'Zhejiang', cn: '浙江省' },
  { en: 'Beijing', cn: '北京市' },
  { en: 'Shanghai', cn: '上海市' },
  { en: 'Sichuan', cn: '四川省' },
  { en: 'Hunan', cn: '湖南省' },
  { en: 'Hubei', cn: '湖北省' },
  { en: 'Jiangsu', cn: '江苏省' },
  { en: 'Anhui', cn: '安徽省' },
  { en: 'Fujian', cn: '福建省' },
  { en: 'Shandong', cn: '山东省' },
  { en: 'Henan', cn: '河南省' },
  { en: 'Hebei', cn: '河北省' },
  { en: 'Shanxi', cn: '山西省' },
  { en: 'Liaoning', cn: '辽宁省' },
  { en: 'Jilin', cn: '吉林省' },
  { en: 'Heilongjiang', cn: '黑龙江省' },
  { en: 'Yunnan', cn: '云南省' },
  { en: 'Guizhou', cn: '贵州省' },
  { en: 'Jiangxi', cn: '江西省' },
  { en: 'Shaanxi', cn: '陕西省' },
  { en: 'Gansu', cn: '甘肃省' },
  { en: 'Qinghai', cn: '青海省' },
  { en: 'Guangxi', cn: '广西壮族自治区' },
  { en: 'Inner Mongolia', cn: '内蒙古自治区' },
  { en: 'Tibet', cn: '西藏自治区' },
  { en: 'Ningxia', cn: '宁夏回族自治区' },
  { en: 'Xinjiang', cn: '新疆维吾尔自治区' },
  { en: 'Hainan', cn: '海南省' },
  { en: 'Chongqing', cn: '重庆市' },
  { en: 'Tianjin', cn: '天津市' },
  { en: 'HongKong', cn: '香港特别行政区' },
  { en: 'Macau', cn: '澳门特别行政区' },
  { en: 'Taiwan', cn: '台湾省' }
]

export function toMapData(raw) {
  return raw.map(item => {
    const match = provinceMap.find(p => p.en === item.province_en)

    return {
      name: match?.cn,      
      value: item.value,    
      en: item.province_en  
    }
  })
}
