"""Bootstrap for the small willow-only app. Reuse NVIDIA read-only; no model self-check."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,importlib,importlib.util,json,logging,os,sys,traceback,uuid
APP_ROOT=Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE=APP_ROOT/"NVIDIA"
DLL_HANDLES=[]
STREAMS=[]
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    temporary.replace(path)
def relative_path(value,root):
    p=Path(value).expanduser()
    return p.resolve() if p.is_absolute() else (root/p).resolve()
def read_settings(app_root):
    path=app_root/"config/settings.json"
    if not path.exists():return {}
    doc=json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(doc,dict):raise ValueError("config/settings.json 必须是JSON对象。")
    return doc
def configure(app_root,package):
    runtime=package/"runtime"
    if not (runtime/"pythonw.exe").is_file() or not (package/"app").is_dir():
        raise FileNotFoundError("模型包目录不完整，缺少 runtime/pythonw.exe 或 app："+str(package))
    if app_root==package or app_root.is_relative_to(package):
        raise ValueError("请把柳莺应用目录与 NVIDIA 模型包目录分开放置。")
    standard=[str(Path(p).resolve()) for p in sys.path if p and Path(p).resolve().is_relative_to(runtime)]
    layers=[app_root,package/"app",runtime/"packages/primary",runtime/"packages/cuda",runtime/"packages/base",runtime/"Lib",runtime/"DLLs",runtime]
    sys.path[:]=list(dict.fromkeys([str(p) for p in layers if p.exists()]+standard))
    sys.dont_write_bytecode=True
    for name in list(os.environ):
        if name in ("PYTHONHOME","PYTHONPATH","CUDA_HOME") or name.startswith("CUDA_PATH"):os.environ.pop(name,None)
    windows=Path(os.environ.get("SystemRoot",r"C:\Windows"))
    os.environ["PATH"]=os.pathsep.join(map(str,(runtime,runtime/"DLLs",windows/"System32",windows)))
    values={"OPENBLAS_NUM_THREADS":"4","OMP_NUM_THREADS":"4","MKL_NUM_THREADS":"4",
            "HF_HUB_OFFLINE":"1","TRANSFORMERS_OFFLINE":"1","HF_HUB_DISABLE_TELEMETRY":"1",
            "YOLO_OFFLINE":"true","YOLO_AUTOINSTALL":"false","PIP_DISABLE_PIP_VERSION_CHECK":"1",
            "TCL_LIBRARY":str(runtime/"tcl/tcl8.6"),"TK_LIBRARY":str(runtime/"tcl/tk8.6"),
            "HF_HOME":str(app_root/"cache/huggingface"),"HF_HUB_CACHE":str(app_root/"cache/huggingface/hub"),
            "TORCH_HOME":str(app_root/"cache/torch"),"TORCH_EXTENSIONS_DIR":str(app_root/"cache/torch_extensions"),
            "XDG_CACHE_HOME":str(app_root/"cache"),"MPLCONFIGDIR":str(app_root/"cache/matplotlib"),
            "YOLO_CONFIG_DIR":str(app_root/"cache/ultralytics")}
    os.environ.update(values)
    for folder in (app_root/"logs",app_root/"results",app_root/"cache",app_root/"cache/ultralytics",
                   app_root/"cache/huggingface",app_root/"cache/torch",app_root/"cache/matplotlib"):
        folder.mkdir(parents=True,exist_ok=True)
    if os.name=="nt":
        for folder in (runtime,runtime/"DLLs",runtime/"packages/cuda/torch/lib"):
            if folder.is_dir():DLL_HANDLES.append(os.add_dll_directory(str(folder)))
    if sys.stdout is None:
        stream=(app_root/"logs/python.log").open("a",encoding="utf-8",buffering=1);STREAMS.append(stream);sys.stdout=stream
    if sys.stderr is None:sys.stderr=sys.stdout
    logging.basicConfig(filename=app_root/"logs/bootstrap.log",encoding="utf-8",level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    os.chdir(app_root)
class NoModelsDuringStartup:
    BLOCKED={"torch","torchvision","open_clip","timm","ultralytics"}
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split(".",1)[0] in self.BLOCKED:
            raise ImportError("启动检查禁止导入视觉模型模块："+fullname)
        return None
def startup_check(app_root,package,images,launch_id):
    result={"status":"checking","passed":False,"launch_id":launch_id,"utc":datetime.now(timezone.utc).isoformat(),
            "app_root":str(app_root),"package_root":str(package),"python_executable":sys.executable,
            "isolated":bool(sys.flags.isolated),"no_site":bool(sys.flags.no_site),"dont_write_bytecode":sys.dont_write_bytecode,
            "images_argument":[str(p) for p in images],"dependencies":{},"imported_modules":{},"errors":[],
            "models_loaded":False,"CUDA_run":False,"GPU_availability_checked":False}
    for name in ("numpy","scipy","sklearn","PIL","cv2","yaml","torch","torchvision","open_clip","timm","ultralytics","tkinter"):
        try:
            spec=importlib.util.find_spec(name)
            if spec is None:raise ImportError("未找到模块")
            origin=spec.origin
            if origin and origin not in ("built-in","frozen") and not Path(origin).resolve().is_relative_to(package/"runtime"):
                raise ImportError("依赖来自模型包运行库以外："+origin)
            result["dependencies"][name]=origin
        except Exception as error:result["errors"].append({"module":name,"error":str(error)})
    blocker=NoModelsDuringStartup();sys.meta_path.insert(0,blocker)
    original_np_load=None;np=None
    try:
        for name in ("numpy","PIL.Image","tkinter"):
            module=importlib.import_module(name);result["imported_modules"][name]=str(getattr(module,"__file__","built-in"))
        np=sys.modules.get("numpy")
        if np is not None:
            original_np_load=np.load
            def forbidden_array_load(*args,**kwargs):raise RuntimeError("启动检查禁止打开模型/特征数组。")
            np.load=forbidden_array_load
        for name in ("app.backend","app.gui"):
            try:
                module=importlib.import_module(name)
                origin=Path(module.__file__).resolve()
                if not origin.is_relative_to(app_root/"app"):raise ImportError("导入的应用模块来源不正确："+str(origin))
                result["imported_modules"][name]=str(origin)
                if name=="app.gui" and not callable(getattr(module,"main",None)):raise ImportError("app.gui.main 入口不存在")
            except Exception as error:result["errors"].append({"module":name,"error":str(error)})
    except Exception as error:result["errors"].append({"module":"startup imports","error":str(error)})
    finally:
        if np is not None and original_np_load is not None:np.load=original_np_load
        sys.meta_path.remove(blocker)
    result["torch_imported"]="torch" in sys.modules
    if result["torch_imported"]:result["errors"].append({"module":"torch","error":"无模型启动检查不应导入torch"})
    result["passed"]=not result["errors"];result["status"]="passed" if result["passed"] else "failed"
    result["sys_path"]=sys.path;result["cache_root"]=str(app_root/"cache");result["output_root"]=str(app_root/"results")
    save(app_root/"logs/startup_check.json",result)
    return 0 if result["passed"] else 1
def main():
    parser=argparse.ArgumentParser(description="柳莺识别轻量启动器")
    parser.add_argument("--app-root",type=Path,default=APP_ROOT)
    parser.add_argument("--package-root",type=Path)
    parser.add_argument("--caller-cwd",type=Path,default=Path.cwd())
    parser.add_argument("--launch-id",default=uuid.uuid4().hex)
    parser.add_argument("--startup-check",action="store_true")
    parser.add_argument("images",nargs="*")
    args=parser.parse_args()
    app_root=args.app_root.resolve()
    if app_root!=APP_ROOT:raise ValueError("app_root必须是本启动脚本所在应用目录。")
    config=read_settings(app_root)
    package=relative_path(args.package_root or config.get("package_root") or DEFAULT_PACKAGE,app_root)
    configure(app_root,package)
    images=tuple(str(relative_path(p,args.caller_cwd.resolve())) for p in args.images)
    config=dict(config);config["package_root"]=str(package)
    # Preserve an explicit launcher override when older GUI settings also exist.
    config["_resolved_package_root"]=str(package)
    if args.startup_check:return startup_check(app_root,package,images,args.launch_id)
    if os.name=="nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:pass
    # Acquire ownership before importing the GUI, torch or any visual models.
    from app.instance import SingleInstance
    instance=SingleInstance()
    try:
        if not instance.primary:
            instance.notify(images)
            logging.info('已唤回现有窗口，当前重复启动退出')
            return 0
        gui=importlib.import_module("app.gui")
        value=gui.main(app_root,package,images=images,config=config,instance=instance)
        return value if isinstance(value,int) else 0
    finally:
        instance.close()
if __name__=="__main__":
    try:raise SystemExit(main())
    except SystemExit:raise
    except Exception as error:
        APP_ROOT.joinpath("logs").mkdir(parents=True,exist_ok=True)
        detail=traceback.format_exc();(APP_ROOT/"logs/startup_error.log").write_text(detail,encoding="utf-8")
        if "--startup-check" in sys.argv:
            save(APP_ROOT/"logs/startup_check.json",{"status":"failed","passed":False,"errors":[str(error)],
                 "models_loaded":False,"CUDA_run":False,"app_root":str(APP_ROOT)})
        else:
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None,str(error)+"\n\n详细日志："+str(APP_ROOT/"logs/startup_error.log"),"柳莺识别启动失败",0x10)
            except Exception:pass
        raise SystemExit(1)
