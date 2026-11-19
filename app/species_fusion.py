"""Frozen species-mass inference. NumPy only; no research-folder dependency."""
from pathlib import Path
import hashlib,json
import numpy as np

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def unit(x):
    x=np.asarray(x,np.float64);n=np.linalg.norm(x,axis=1,keepdims=True)
    if not np.isfinite(x).all() or (n<=1e-12).any():raise ValueError('Invalid BioCLIP features')
    return x/n
def softmax(x):
    p=np.exp(x-x.max(1,keepdims=True));return p/p.sum(1,keepdims=True)

class SpeciesMassFusion:
    def __init__(self,path):
        self.path=Path(path).resolve();self.manifest=read(self.path);m=self.manifest
        if m['schema']!='willow-species-mass-runtime-v1':raise ValueError('Unknown fusion schema')
        asset=(self.path.parent/m['asset']).resolve()
        if not asset.is_relative_to(self.path.parent)or sha(asset)!=m['asset_sha256']:raise ValueError('Fusion checksum mismatch')
        with np.load(asset,allow_pickle=False)as z:self.a={k:z[k]for k in z.files}
        self.classes=m['classes'];self.n=len(self.classes);a=self.a
        if self.n!=57 or len(set(self.classes))!=57:raise ValueError('Invalid fusion class order')
        expected={'keys':(len(a['keys']),1792),'values':(len(a['keys']),57),'text':(57,1792),
            'gda_W':(1792,57),'gda_b':(57,),'mean':(171,),'scale':(171,),
            'expert_bias':(3,),'weight':(171,60),'bias':(60,)}
        if set(a)!=set(expected)or any(a[k].shape!=s or not np.isfinite(a[k]).all()for k,s in expected.items())or(a['scale']<=0).any():raise ValueError('Invalid fusion arrays')
        self.binding={'version':m['schema'],'model_name':'物种概率融合版','manifest_sha256':sha(self.path),
            'asset_sha256':m['asset_sha256'],'species_count':57,'extra_visual_forwards':0,
            'reference_model_sha256':m['source_species_mass_sha256'],'confidence_is_accuracy':False}

    def predict57(self,features,current):
        c=np.asarray(current,np.float64);a=self.a
        if c.ndim!=2 or c.shape[1]!=57 or not np.isfinite(c).all()or(c<0).any()or not np.allclose(c.sum(1),1):raise ValueError('Invalid current probabilities')
        f2,f25=unit(features['bio2']),unit(features['bio25'])
        if f2.shape!=(len(c),768)or f25.shape!=(len(c),1024):raise ValueError('Feature/crop row mismatch')
        q=np.concatenate((f2,f25),1)/np.sqrt(2)
        text_logits = (100 * q) @ a['text'].T
        tip=softmax(text_logits+.5*(np.exp(20*(q@a['keys'].T-1))@a['values']))
        gda=softmax(text_logits+self.manifest['GDA_alpha']*(q@a['gda_W']+a['gda_b']))
        experts=np.stack((c,tip,gda),axis=1);e=np.clip(experts,1e-5,1-1e-5)
        x=((np.log(e)-np.log1p(-e)).reshape(len(c),-1)-a['mean'])/a['scale']
        skip=np.concatenate((np.log(np.maximum(c,1e-5)),np.tile(a['expert_bias'],(len(c),1))),1)
        s=softmax(skip+x@a['weight']+a['bias']);p=s[:,:57].copy();idx=np.arange(len(c))
        for j in range(3):np.add.at(p,(idx,experts[:,j].argmax(1)),s[:,57+j])
        return p

    def predict(self,features,current,class_names):
        original=np.asarray(current,np.float64);names=list(class_names)
        if original.ndim!=2 or original.shape[1]!=len(names)or len(set(names))!=len(names)or not np.isfinite(original).all()or(original<0).any()or not np.allclose(original.sum(1),1):raise ValueError('Invalid application probabilities')
        if not set(self.classes).issubset(names):raise ValueError('Fusion species missing')
        cols=np.array([names.index(s)for s in self.classes]);eligible=np.isin(original.argmax(1),cols);ix=np.flatnonzero(eligible);out=original.copy()
        if len(ix):
            c=original[np.ix_(ix,cols)];c=c/c.sum(1,keepdims=True)
            p=self.predict57({k:np.asarray(features[k])[ix]for k in ('bio2','bio25')},c)
            out[ix]=0;out[np.ix_(ix,cols)]=p
        return {'probabilities':out,'predicted_index':out.argmax(1),'fusion_applied':eligible,
            'before_fusion_probabilities':original.copy(),'fusion_binding':self.binding}

def load_active(app,head):
    path=Path(app)/'config/species_fusion.json'
    if not path.exists():return None
    config=read(path)
    if config.get('schema')!='willow-species-fusion-config-v1':raise ValueError('Unknown active fusion config')
    if not config.get('enabled'):return None
    manifest=(Path(app)/config['manifest']).resolve()
    if not manifest.is_relative_to((Path(app)/'models').resolve())or sha(manifest)!=config['manifest_sha256']:raise ValueError('Active fusion manifest mismatch')
    runtime=SpeciesMassFusion(manifest);m=runtime.manifest
    if m['base_manifest_sha256']!=head.manifest_sha256 or m['group_review_config_sha256']!=head.group_review_config_sha256:raise ValueError('Fusion requires its frozen base/group review')
    return runtime
