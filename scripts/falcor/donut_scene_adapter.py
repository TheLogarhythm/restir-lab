"""Plan and apply a Donut scene.json to Falcor without silent loss of scene data.

The caller must supply a model_loader(path, row_major_world_matrix) that preserves
model transforms, and must freeze the runtime scene/camera as recorded in the plan.
This module does not implement Donut area lights, per-light IES, or procedural sky;
all approximations require an explicit, named policy and are recorded per node.
"""
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import unquote, urlsplit


_APPROXIMATIONS = {
    'light_radius': 'delta',
    'light_range': 'unbounded',
    'light_ies': 'omit',
    'sun_angular_size': 'delta',
    'rtxdi_spot_falloff': 'donut_angular',
    'rect_area_light': 'point',
    'procedural_environment': ('hdr_substitute', 'baked_hdr'),
}


def parse_jsonc(text):
    """Parse JSON plus C-style comments and trailing commas, preserving strings."""
    if text.startswith('\ufeff'):
        text = text[1:]
    out=[]; i=0; in_string=False; escape=False
    while i < len(text):
        c=text[i]
        if in_string:
            out.append(c)
            if escape: escape=False
            elif c=='\\': escape=True
            elif c=='"': in_string=False
            i+=1; continue
        if c=='"': in_string=True; out.append(c); i+=1; continue
        if text.startswith('//',i):
            end=text.find('\n',i+2)
            if end<0: break
            out.append('\n'); i=end+1; continue
        if text.startswith('/*',i):
            end=text.find('*/',i+2)
            if end<0: raise ValueError('Unterminated JSON comment')
            out.append(' '); i=end+2; continue
        out.append(c); i+=1
    if in_string: raise ValueError('Unterminated JSON string')
    text=''.join(out); out=[]; i=0; in_string=False; escape=False
    while i<len(text):
        c=text[i]
        if in_string:
            out.append(c)
            if escape: escape=False
            elif c=='\\': escape=True
            elif c=='"': in_string=False
            i+=1; continue
        if c=='"': in_string=True; out.append(c); i+=1; continue
        if c==',':
            j=i+1
            while j<len(text) and text[j].isspace():j+=1
            if j<len(text) and text[j] in '}]':i+=1;continue
        out.append(c);i+=1
    try:return json.loads(''.join(out))
    except json.JSONDecodeError as exc:raise ValueError('Invalid scene JSON: '+str(exc)) from exc


def _digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def _resolve_uri(base, uri, root):
    if not isinstance(uri,str) or not uri:raise ValueError('Empty asset URI')
    parsed=urlsplit(uri)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError('Only local relative asset URIs are supported: '+uri)
    raw=unquote(parsed.path)
    if Path(raw).is_absolute() or '\\' in raw:
        raise ValueError('Only local forward-slash relative asset URIs are supported: '+uri)
    path=(base/raw).resolve()
    if not path.is_relative_to(root):raise ValueError('Asset escapes configured root: '+uri)
    if not path.is_file():raise FileNotFoundError(path)
    return path


def _number(value, name):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError('Expected finite numeric '+name)
    return float(value)


def _vec(value, n, name):
    if not isinstance(value,(list,tuple)) or len(value)!=n:raise ValueError('Expected '+name+' vector length '+str(n))
    return [_number(x,name) for x in value]


def _matrix(node):
    t=_vec(node.get('translation',[0,0,0]),3,'translation')
    q=_vec(node.get('rotation',[0,0,0,1]),4,'rotation')
    length=math.sqrt(sum(v*v for v in q))
    if length<1e-12 or abs(length-1)>1e-3:raise ValueError('Rotation quaternion is not unit length')
    x,y,z,w=[v/length for v in q]
    scale=node.get('scaling',1)
    s=_vec(scale,3,'scaling') if isinstance(scale,(list,tuple)) else [_number(scale,'scaling')]*3
    if any(abs(v)<1e-12 for v in s):raise ValueError('Singular scene node scaling')
    r=[[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
       [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
       [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]
    return [[r[i][j]*s[j] for j in range(3)]+[t[i]] for i in range(3)]+[[0.,0.,0.,1.]]


def _multiply(a,b):
    return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _direction(matrix):
    d=[-matrix[i][2] for i in range(3)]; length=math.sqrt(sum(x*x for x in d))
    if length<1e-12:raise ValueError('Degenerate light direction')
    return [x/length for x in d]


def plan_scene(scene_file, asset_root, *, animation_policy='reject', camera_policy='reject',
               environment=None, approximations=None, ignored_top_level=None, ies_dirs=None,
               source_lighting_model=None):
    """Return a serializable scene plan; no Falcor device or renderer is required.

    Approximations must map the precise issue code to its documented selected mode.
    `source_default_disabled` does not apply an animation at time zero.
    `camera_policy=external` records source cameras; caller must set a fixed camera.
    """
    scene_file=Path(scene_file).resolve(strict=True);root=Path(asset_root).resolve(strict=True)
    if not scene_file.is_relative_to(root):raise ValueError('Scene file outside asset root')
    data=parse_jsonc(scene_file.read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict):raise ValueError('Scene root must be an object')
    policies=dict(approximations or {});ignored=dict(ignored_top_level or {})
    for code,mode in policies.items():
        allowed=_APPROXIMATIONS.get(code)
        if allowed is None or mode not in ((allowed,) if isinstance(allowed,str) else allowed):
            raise ValueError('Unknown approximation policy: '+str(code)+'='+str(mode))
    if source_lighting_model not in (None,'donut','rtxdi_fullsample'):raise ValueError('Unknown source lighting model')
    if animation_policy not in ('reject','source_default_disabled'):raise ValueError('Unknown animation policy')
    if camera_policy not in ('reject','external'):raise ValueError('Unknown camera policy')
    deps={};issues=[];actions=[];cameras=[]
    def dep(path,kind):
        path=Path(path).resolve(strict=True)
        if not path.is_file():raise ValueError('Dependency is not a file: '+str(path))
        with path.open('rb') as f:
            if f.read(42).startswith(b'version https://git-lfs.github.com/spec/v1'):
                raise ValueError('Unresolved Git LFS dependency: '+str(path))
        key=str(path); old=deps.get(key)
        if old is None:deps[key]={'path':key,'sha256':_digest(path),'kinds':[kind]}
        elif kind not in old['kinds']:old['kinds'].append(kind)
        return key
    def issue(code,path,detail,*,allow=False):
        accepted=allow and code in policies
        issues.append({'code':code,'node_path':path,'severity':'approximation' if accepted else 'error',
                       'detail':detail,'selected_policy':policies.get(code) if accepted else None})
    dep(scene_file,'scene')
    models=data.get('models',[])
    if not isinstance(models,list) or any(not isinstance(m,str) for m in models):raise ValueError('models must be an array of paths')
    model_paths=[]
    for m in models:
        p=_resolve_uri(scene_file.parent,m,root);model_paths.append(p);dep(p,'model')
        if p.suffix.lower()=='.gltf':
            gltf=json.loads(p.read_text(encoding='utf-8-sig'))
            for entry in gltf.get('buffers',[]):
                uri=entry.get('uri','')
                if uri and not uri.startswith('data:'):dep(_resolve_uri(p.parent,uri,root),'gltf_buffer')
            images=gltf.get('images',[])
            for texture in gltf.get('textures',[]):
                ext=texture.get('extensions',{}).get('MSFT_texture_dds')
                index=ext.get('source') if ext is not None else texture.get('source')
                if type(index) is not int or not 0<=index<len(images):raise ValueError('Missing/invalid glTF texture source')
                image=images[index];uri=image.get('uri','')
                if uri and not uri.startswith('data:'):dep(_resolve_uri(p.parent,uri,root),'gltf_texture')
                elif not uri and 'bufferView' not in image:raise ValueError('Unsupported glTF image source')
        else:
            issue('model_dependency_unknown',m,'External model resources cannot be inventoried automatically')
    allowed_top={'models','graph','animations','helpers'}
    for key,value in data.items():
        if key in allowed_top:continue
        if key in ignored and isinstance(ignored[key],str) and ignored[key].strip():continue
        issue('top_level_unsupported','/',key)
    for key,reason in ignored.items():
        if key not in data or key in allowed_top or not isinstance(reason,str) or not reason.strip():
            raise ValueError('Invalid explicit ignored top-level field: '+str(key))
    animations=data.get('animations',[])
    if not isinstance(animations,list):raise ValueError('animations must be an array')
    if animations and animation_policy=='reject':issue('animation_policy','/','Explicitly select source_default_disabled or implement animations')
    identity=[[1.,0.,0.,0.],[0.,1.,0.,0.],[0.,0.,1.,0.],[0.,0.,0.,1.]]
    ies_search_dirs = ies_dirs if ies_dirs is not None else ([root/'ies-profiles'] if (root/'ies-profiles').is_dir() else [])
    ies_roots=[Path(x).resolve(strict=True) for x in ies_search_dirs]
    if any(not p.is_dir() or not p.is_relative_to(root) for p in ies_roots):
        raise ValueError('IES directories must reside under the asset root')
    common={'name','type','model','translation','rotation','scaling','children'}
    light_fields={'color','intensity','irradiance','radius','range','innerAngle','outerAngle','angularSize','profile'}
    camera_fields={'verticalFov','zNear','zFar','aspectRatio','xMag','yMag'}
    def visit(node,parent,index_path):
        if not isinstance(node,dict):raise ValueError('Scene graph nodes must be objects')
        name=node.get('name','')
        if not isinstance(name,str):raise ValueError('Node name must be a string')
        path=index_path+(':'+name if name else '')
        world=_multiply(parent,_matrix(node));typ=node.get('type')
        allowed=common | (light_fields if typ in ('PointLight','SpotLight','DirectionalLight','RectLight') else camera_fields if typ in ('PerspectiveCamera','OrthographicCamera') else set())
        for key in node:
            if key not in allowed:issue('node_field_unsupported',path,key)
        if 'model' in node:
            idx=node['model']
            if type(idx) is not int or idx<0 or idx>=len(model_paths):raise ValueError('Invalid model index at '+path)
            actions.append({'kind':'model','node_path':path,'model_index':idx,'source':str(model_paths[idx]),'world_matrix':world})
        if typ in ('PerspectiveCamera','OrthographicCamera'):
            cameras.append({'node_path':path,'type':typ,'source':dict(node),'world_matrix':world})
            if camera_policy!='external':issue('camera_policy',path,'Select and set external fixed camera explicitly')
        elif typ in ('PointLight','SpotLight','DirectionalLight','RectLight'):
            if source_lighting_model is None:
                issue('source_lighting_model',path,'Choose donut or rtxdi_fullsample explicitly')
            source={k:v for k,v in node.items() if k not in ('children','model')}
            color=_vec(node.get('color',[1,1,1]),3,'light color')
            if any(v<0 for v in color):raise ValueError('Negative light color')
            action={'kind':'light','type':typ,'node_path':path,'source':source,'world_matrix':world,
                    'position':[world[i][3] for i in range(3)],'direction':_direction(world),'color':color}
            if typ=='DirectionalLight':
                action['irradiance']=_number(node.get('irradiance',1),'irradiance')
                action['angular_size_degrees']=_number(node.get('angularSize',0),'angularSize')
                if action['angular_size_degrees']<0 or action['angular_size_degrees']>90:raise ValueError('Unsupported angularSize')
                if action['angular_size_degrees']>0:issue('sun_angular_size',path,'Finite angular source approximated by a delta directional light',allow=True)
            elif typ in ('PointLight','SpotLight'):
                for key in ('intensity','radius','range'):
                    action[key]=_number(node.get(key,1 if key=='intensity' else 0),key)
                    if action[key]<0:raise ValueError('Negative '+key)
                if action['radius']>0:issue('light_radius',path,'Finite radius becomes delta light',allow=True)
                if source_lighting_model=='rtxdi_fullsample':
                    action['source_range_semantics']='RTXDI FullSample ConvertLight does not use range'
                elif action['range']>0:issue('light_range',path,'Donut finite range becomes unbounded',allow=True)
                if typ=='SpotLight':
                    action['inner_angle_degrees']=_number(node.get('innerAngle',180),'innerAngle')
                    action['outer_angle_degrees']=_number(node.get('outerAngle',180),'outerAngle')
                    if not 0<=action['inner_angle_degrees']<=action['outer_angle_degrees']<=180:raise ValueError('Invalid spotlight cone')
                    if source_lighting_model=='rtxdi_fullsample':
                        issue('rtxdi_spot_falloff',path,'RTXDI FullSample uses a cosine-space smoothstep and quantized parameters; Falcor uses Donut angular-space smoothstep',allow=True)
            else:
                action['flux']=_number(node.get('flux',0),'flux')
                issue('rect_area_light',path,'Rect area light approximated by isotropic point from flux/(4 pi)',allow=True)
            if typ=='DirectionalLight' and action['irradiance']<0:raise ValueError('Negative irradiance')
            profile=node.get('profile','')
            if profile:
                if not isinstance(profile,str) or Path(profile).name!=profile:raise ValueError('Invalid light profile name')
                matches=[r/profile for r in ies_roots if (r/profile).is_file()]
                if len(matches)!=1:raise ValueError('IES profile absent or ambiguous: '+profile)
                action['ies_path']=dep(matches[0],'ies_profile')
                issue('light_ies',path,'Per-light IES profile not implemented by this Falcor adapter',allow=True)
            actions.append(action)
        elif typ is not None:
            issue('unknown_node_type',path,str(typ))
        children=node.get('children',[])
        if not isinstance(children,list):raise ValueError('children must be an array')
        for i,child in enumerate(children):visit(child,world,path+'/children['+str(i)+']')
    graph=data.get('graph',[])
    if not isinstance(graph,list):raise ValueError('graph must be an array')
    for i,node in enumerate(graph):visit(node,identity,'/graph['+str(i)+']')
    helpers=data.get('helpers',[])
    if helpers not in (None,[]):issue('helpers_unsupported','/','Non-empty helpers')
    env={'source_kind':None,'effective_kind':None}
    if environment is None:
        issue('environment_unspecified','/','Explicitly specify none, HDR, or procedural source')
    else:
        if not isinstance(environment,dict):raise ValueError('environment must be an object')
        kind=environment.get('kind');env['source_kind']=kind
        allowed_environment={'kind'} if kind=='none' else {'kind','path','intensity_ev','rotation_degrees'} if kind=='hdr' else {'kind','baked_hdr','bake_receipt','fallback_hdr','intensity_ev','rotation_degrees'}
        unexpected=set(environment)-allowed_environment
        if unexpected:raise ValueError('Unsupported environment fields: '+str(sorted(unexpected)))
        if kind=='none':env['effective_kind']='none'
        elif kind in ('hdr','procedural'):
            if kind=='hdr':image=environment.get('path')
            else:
                mode=policies.get('procedural_environment')
                image=environment.get('baked_hdr') if mode=='baked_hdr' else environment.get('fallback_hdr')
                if mode=='baked_hdr':
                    receipt=environment.get('bake_receipt')
                    if not receipt:raise ValueError('baked_hdr requires a bake_receipt')
                    env['bake_receipt']=dep(Path(receipt),'environment_bake_receipt')
                issue('procedural_environment','/','Procedural sky represented by selected HDR; inspect source and quantization limitations',allow=True)
            if image:
                env['path']=dep(Path(image),'environment_hdr');env['effective_kind']='hdr'
            elif kind=='hdr':raise ValueError('HDR path required')
            env['intensity_ev']=_number(environment.get('intensity_ev',0),'environment intensity_ev')
            rotation=environment.get('rotation_degrees',0)
            env['rotation_degrees']=_vec(rotation,3,'environment rotation') if isinstance(rotation,(list,tuple)) else [0.,_number(rotation,'environment rotation'),0.]
            env['source_config']={k:str(v) if isinstance(v,Path) else v for k,v in environment.items()}
        else:raise ValueError('Unknown environment kind')
    return {'schema_version':1,'scene_file':str(scene_file),'asset_root':str(root),
            'dependencies':sorted(deps.values(),key=lambda x:x['path']),'actions':actions,'cameras':cameras,
            'animation':{'policy':animation_policy,'source_count':len(animations),'time_zero_applied':False},
            'ignored_top_level':ignored,'environment':env,'issues':issues,'approximations':policies,
            'source_lighting_model':source_lighting_model,
            'runtime_requirements':{'disable_scene_animation':animation_policy=='source_default_disabled','set_external_camera':camera_policy=='external'},
            'validation':'CPU translation plan only; Falcor/light unit and GPU equivalence require separate verification'}


def require_supported(plan):
    errors=[item for item in plan['issues'] if item['severity']=='error']
    if errors:raise ValueError('Scene has unsupported features: '+json.dumps(errors,ensure_ascii=False))
    if plan['environment']['effective_kind'] is None:raise ValueError('No effective environment selected')
    return plan


def apply_plan(plan, builder, falcor, model_loader):
    """Apply only after full policy and dependency checks; no unrecorded substitutions.

    model_loader is a required callback taking (absolute_path, world_matrix) for
    each model; its implementation must preserve the matrix. Returns issue records.
    """
    require_supported(plan)
    for item in plan['dependencies']:
        p=Path(item['path'])
        if not p.is_file() or _digest(p)!=item['sha256']:raise ValueError('Scene dependency changed: '+str(p))
    if any(a['kind']=='model' for a in plan['actions']) and not callable(model_loader):
        raise ValueError('Model loader accepting a world matrix is required')
    for action in plan['actions']:
        if action['kind']=='model':model_loader(action['source'],action['world_matrix']);continue
        typ=action['type'];name=action['node_path']
        if typ=='DirectionalLight':light=falcor.DirectionalLight(name);light.direction=falcor.float3(*action['direction']);magnitude=action['irradiance']
        else:
            light=falcor.PointLight(name);light.position=falcor.float3(*action['position'])
            if typ=='SpotLight':
                light.direction=falcor.float3(*action['direction']);light.openingAngle=math.radians(action['outer_angle_degrees']);light.penumbraAngle=math.radians(action['outer_angle_degrees']-action['inner_angle_degrees'])
            magnitude=action['flux']/(4*math.pi) if typ=='RectLight' else action['intensity']
        light.intensity=falcor.float3(*(x*magnitude for x in action['color']));builder.addLight(light)
    env=plan['environment']
    if env['effective_kind']=='hdr':
        e=falcor.EnvMap(env['path']);e.intensity=2**env['intensity_ev'];e.rotation=falcor.float3(*env['rotation_degrees']);builder.envMap=e
    else:
        builder.envMap=None
    return list(plan['issues'])
