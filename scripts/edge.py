"""YOLO edge inference/video extraction and ONNX/TensorRT export."""
import argparse,json,time
from pathlib import Path

def main():
    import os
    os.environ.setdefault('YOLO_CONFIG_DIR',str(Path(__file__).resolve().parents[1]/'runtime/yolo-config'))
    (Path(os.environ['YOLO_CONFIG_DIR'])/'Ultralytics').mkdir(parents=True,exist_ok=True)
    p=argparse.ArgumentParser();p.add_argument('action',choices=['infer','export']);p.add_argument('--weights',required=True);p.add_argument('--source');p.add_argument('--output',required=True);p.add_argument('--device',default='cpu');p.add_argument('--format',default='onnx',choices=['onnx','engine']);p.add_argument('--int8',action='store_true');p.add_argument('--calibration-data');p.add_argument('--video-stride',type=int,default=30);a=p.parse_args()
    from ultralytics import YOLO
    model=YOLO(a.weights);out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    if a.action=='export':
        import shutil
        copied=out/Path(a.weights).name
        if Path(a.weights).resolve()!=copied.resolve():shutil.copy2(a.weights,copied)
        model=YOLO(str(copied))
        if a.int8 and (a.format!='engine' or not a.calibration_data):raise ValueError('INT8 requires TensorRT and representative calibration dataset')
        exported=model.export(format=a.format,int8=a.int8,data=a.calibration_data,device=a.device,imgsz=640)
        (out/'export.json').write_text(json.dumps({'exported':str(exported),'weights':a.weights,'format':a.format,'int8':a.int8}))
        return
    if not a.source:raise ValueError('--source required for inference')
    records=[]
    for i,result in enumerate(model.predict(a.source,stream=True,device=a.device,vid_stride=a.video_stride,verbose=False)):
        detections=[]
        for j,box in enumerate(result.boxes):
            xyxy=box.xyxy[0].int().tolist();x1,y1,x2,y2=xyxy
            import cv2
            crop=out/f'{i:06d}-{j:03d}.jpg';cv2.imwrite(str(crop),result.orig_img[y1:y2,x1:x2])
            detections.append({'bbox':xyxy,'label':model.names[int(box.cls[0])],'confidence':float(box.conf[0]),'crop':str(crop)})
        records.append({'frame':i,'source':str(a.source),'timestamp':time.time(),'detections':detections,'missing_components_inferred':False})
    (out/'detections.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
