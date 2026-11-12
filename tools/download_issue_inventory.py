"""Read-only pack/task inventory; never reads or prints account credentials."""
import json
from pathlib import Path
import zipfile

root=Path('E:/code')
for path in root.iterdir():
    if path.suffix.lower() not in ('.zip','.mrpack'):continue
    try:
        with zipfile.ZipFile(path) as archive:
            names=archive.namelist()
            manifests=[name for name in names if name.rsplit('/',1)[-1] in ('manifest.json','modrinth.index.json','buggcraft.pack.json')]
            details=[]
            for name in manifests[:2]:
                if archive.getinfo(name).file_size>4*1024*1024:continue
                data=json.loads(archive.read(name))
                details.append(dict(manifest=name,game=data.get('minecraft',data.get('dependencies')),files=len(data.get('files',[]))))
            print(json.dumps(dict(pack=path.name,size=path.stat().st_size,entries=len(names),details=details),ensure_ascii=False))
    except (ValueError,OSError,zipfile.BadZipFile) as error:print(path.name,type(error).__name__)
path=root/'bugg/build/.buggcraft/instance-settings.json'
if path.exists():
    data=json.loads(path.read_text(encoding='utf-8'))
    for task in data.get('tasks',[]):
        if task.get('state') in ('failed','interrupted','cancelled'):
            summary={key:task.get(key) for key in ('kind','name','state','detail')}
            spec=task.get('specification',{})
            summary['target']={key:spec.get(key) for key in ('id','game','loader','archive')}
            summary['plan']=spec.get('plan',{})
            print(json.dumps(summary,ensure_ascii=False))
cache=root/'bugg/build/.buggcraft'
for path in (cache/'runtime').glob('**/bin/java.exe'):
    import subprocess
    result=subprocess.run([str(path),'-version'],capture_output=True,text=True,timeout=8)
    print(json.dumps(dict(java=str(path.relative_to(cache)),exit=result.returncode,version=(result.stdout+result.stderr)[:350]),ensure_ascii=False))
