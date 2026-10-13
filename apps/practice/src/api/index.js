let bearer = ''
export const setToken = value => { bearer = value || '' }
export async function request(path,options={}) {
 const response=await fetch('/api'+path,{...options,headers:{'Content-Type':'application/json',...(bearer?{Authorization:'Bearer '+bearer}:{}),...options.headers}})
 const data=await response.json().catch(()=>({detail:'无法读取服务响应'}))
 if(!response.ok){if(response.status===401&&path!='/login')window.dispatchEvent(new Event('xf-auth-expired'));const err=new Error(typeof data.detail==='string'?data.detail:response.status===422?'请检查提交内容的格式和照片大小':'请求失败');err.status=response.status;throw err;}return data
}
export const post=(path,body)=>request(path,{method:'POST',body:JSON.stringify(body)})
export const statusLabel=status=>({queued:'已排队',running:'执行中',pending:'待审核',blocked:'待补充 / 验证未通过',approved:'已定稿',returned:'已退回',rejected:'已驳回',failed:'执行失败'}[status]||status)
export function safeSource(url){try{const value=new URL(url);return ['http:','https:'].includes(value.protocol)?value.href:null}catch{return null}}
export async function fileToBase64(file){if(!['image/jpeg','image/png'].includes(file.type)||file.size>10*1024*1024)throw new Error('请选择 ≤10MiB 的 JPEG / PNG 照片');const bitmap=await createImageBitmap(file);const pixels=bitmap.width*bitmap.height;bitmap.close();if(pixels>16000000)throw new Error('照片需小于 1600 万像素');return await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('照片读取失败'));reader.readAsDataURL(file)})}
