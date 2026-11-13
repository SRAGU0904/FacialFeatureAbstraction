"""Offline result organization and galleries. Never accesses credentials or model APIs."""
import argparse
import fcntl
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import tempfile

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = ROOT / 'result-data/ai-results'
NAMES = {'zhu': ('01-Zhu-Yuanzhang.png', '朱元璋'), 'euro': ('02-Rudolf-II.png', '鲁道夫二世')}

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def esc(value):
    return html.escape(str(value), quote=True)

def reserve_group(root, model, reasoning, name=None):
    root = Path(root).resolve()
    prefix = re.sub(r'[^a-zA-Z0-9_.-]', '-', f'{model}_{reasoning}')
    root.mkdir(parents=True, exist_ok=True)
    if name:
        if not re.fullmatch(re.escape(prefix) + r'_\d+', name):
            raise ValueError('--result-group must match model_reasoning_number.')
        group = root / name
        if not (group / 'summary.json').exists():
            raise ValueError('The continuation result group does not exist.')
        summary = read(group / 'summary.json')
        if (summary['model'], summary['reasoning']) != (model, reasoning):
            raise ValueError('Result group model/reasoning mismatch.')
        return group
    number = 1
    while True:
        group = root / f'{prefix}_{number:02d}'
        try:
            group.mkdir()
            break
        except FileExistsError:
            number += 1
    write(group / 'summary.json', {'name': group.name, 'path': group.name,
          'earlierExperiment': False, 'model': model, 'reasoning': reasoning,
          'portraits': [], 'sourceExperiments': [], 'completePair': False,
          'showMissingPortraits': False})
    return group

def check_portraits_available(group, portraits):
    existing = {p['portraitId'] for p in read(group / 'summary.json')['portraits']}
    if existing.intersection(portraits):
        raise ValueError('Result group already contains this portrait; start a new group instead.')

def register_experiment(group, source, move=False):
    # Different models may finish in separate terminals at the same time.
    with (Path(group).parent / '.organization.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _register_experiment(group, source, move)

def _register_experiment(group, source, move=False):
    """Preserve an attempt and expose only completed portraits; never overwrite a result."""
    group, source = Path(group).resolve(), Path(source).resolve()
    summary = read(group / 'summary.json')
    record = read(source / 'experiment.json')
    if record.get('simulated') or record.get('status') == 'running':
        raise ValueError('Only stopped real experiments can enter the result gallery.')
    settings = record['settings']
    if (settings['model'], settings['reasoning']) != (summary['model'], summary['reasoning']):
        raise ValueError('Model/reasoning mismatch; refusing to merge results.')
    # Re-registering the same preserved attempt is harmless.
    for previous in summary['sourceExperiments']:
        if str(source) in (previous['originalPath'], str(group / previous['records'])):
            return group
    completed = [t for t in record.get('trials', []) if t['status'] == 'completed']
    check_portraits_available(group, [t['portraitId'] for t in completed])
    prepared = []
    for trial in completed:
        portrait = trial['portraitId']
        run = source / trial['run']
        before = read(run / 'round-1/feedback.json')['scene']['items']
        after = read(run / 'round-2/feedback.json')['scene']['items']
        final = source / trial['finalPng']
        feedback = read(run / 'round-2/feedback.json')
        if digest(final) != digest(run / 'round-2' / feedback['snapshot']['png']):
            raise ValueError('Final image disagrees with the third-round snapshot.')
        corrections = []
        for pattern in ('round-*/normalization.json', 'round-*/local-recovery.json'):
            for path in sorted((run / 'calls').glob(pattern)):
                corrections.append({'round': int(path.parent.name.split('-')[-1]) + 1, **read(path)})
        explanation = run / 'round-2/explanation.txt'
        filename, label = NAMES[portrait]
        prepared.append((trial, {'portraitId': portrait, 'name': label, 'image': filename,
            'sha256': digest(final), 'settings': settings, 'thirdRoundIdentical': before == after,
            'itemCount': len(after), 'foods': dict(Counter(i['id'] for i in after)),
            'localCorrections': corrections,
            'explanationText': explanation.read_text(encoding='utf-8') if explanation.exists() else '',
            'originalRunPath': str(run)}))
    original_hashes = {str(p.relative_to(source)): digest(p) for p in source.rglob('*') if p.is_file()}
    records_root = group / 'records'
    records_root.mkdir(exist_ok=True)
    internal = source.is_relative_to(records_root)
    if internal:
        stored = source
    else:
        number = 1
        while (records_root / f'attempt-{number:03d}').exists():
            number += 1
        stored = records_root / f'attempt-{number:03d}'
        staging = Path(tempfile.mkdtemp(prefix='.import-', dir=records_root))
        try:
            shutil.copytree(source, staging, dirs_exist_ok=True)
            if any(digest(staging / rel) != sha for rel, sha in original_hashes.items()):
                raise ValueError('Record copy verification failed.')
            staging.rename(stored)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    for trial, item in prepared:
        shutil.copy2(stored / trial['finalPng'], group / item['image'])
        item['recordRun'] = str((stored / trial['run']).relative_to(group))
        summary['portraits'].append(item)
    summary['portraits'].sort(key=lambda p: p['portraitId'] == 'euro')
    summary['completePair'] = {p['portraitId'] for p in summary['portraits']} == set(NAMES)
    summary['sourceExperiments'].append({'originalPath': str(source),
        'records': str(stored.relative_to(group)), 'originalExperimentId': record['experimentId']})
    write(group / 'summary.json', summary)
    manifest_path = group.parent / 'organization-manifest.json'
    manifest = read(manifest_path) if manifest_path.exists() else {
        'groups': [], 'copiedFiles': [], 'paidResponses': [], 'sourceMapping': {}}
    mapping = manifest.setdefault('sourceMapping', {})
    mapping[str(source)] = str(stored.relative_to(group.parent))
    for relative, sha in original_hashes.items():
        item = {'source': str(source / relative),
                'destination': str((stored / relative).relative_to(group.parent)), 'sha256': sha}
        manifest.setdefault('copiedFiles', []).append(item)
        if Path(relative).name == 'api-response.json':
            manifest.setdefault('paidResponses', []).append(item)
    manifest['groups'] = [g for g in manifest.get('groups', []) if g['path'] != group.name] + [summary]
    write(manifest_path, manifest)
    refresh_gallery(group.parent)
    if move and not internal:
        current = {str(p.relative_to(source)): digest(p) for p in source.rglob('*') if p.is_file()}
        if current != original_hashes:
            raise ValueError('Source changed during import; original retained.')
        shutil.rmtree(source)
    return group

def figures(entry, prefix=''):
    parts = []
    for item in entry['portraits']:
        change = '第三轮未改布局' if item['thirdRoundIdentical'] else '第三轮修改了布局'
        note = ' · 含本地修正，详见记录' if item.get('localCorrections') else ''
        explanation = ('<details><summary>查看模型解释</summary><pre>' +
                       esc(item['explanationText']) + '</pre></details>') if item.get('explanationText') else ''
        path = esc(prefix + item['image'])
        parts.append(f'<figure><a href="{path}"><img loading="lazy" src="{path}" alt="{esc(item["name"])}"></a>'
                     f'<figcaption>{esc(item["name"])}</figcaption><div class="meta">'
                     f'{item["itemCount"]} 个食物实例 · {change}{note}</div>{explanation}</figure>')
    return '<div class="pair">' + ''.join(parts) + '</div>'

def page(title, body):
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>' + esc(title) + '</title><style>' + STYLE + '</style><main>' + body + '</main></html>'

def refresh_gallery(root=DEFAULT_ROOT):
    root = Path(root)
    paths = list(root.glob('*/summary.json')) + list(root.glob('archive/earlier-experiments/*/summary.json'))
    groups = [read(path) for path in paths]
    for path, group in zip(paths, groups):
        group['path'] = str(path.parent.relative_to(root))
        note = '双图结果齐全。' if group['completePair'] else '仅展示已完成作品，未完成的调用记录保存在 records 中。'
        (path.parent / 'index.html').write_text(page(group['name'],
            f'<header><h1>{esc(group["name"])}</h1><p>{note}</p></header>' + figures(group) +
            '<footer>完整逐轮输出、解释和 token 用量保存在 records 文件夹。</footer>'), encoding='utf-8')
    formal = sorted((g for g in groups if not g.get('earlierExperiment') and g['portraits']), key=lambda g:g['name'])
    early = sorted((g for g in groups if g.get('earlierExperiment')), key=lambda g:g['name'])
    def cards(entries):
        return ''.join(f'<section class="card" data-model="{esc(g["model"])}"><h2><a href="{esc(g["path"])}/index.html">{esc(g["name"])}</a></h2>' +
            ('' if g['completePair'] else '<span class="badge">本组尚未完成双图</span>') +
            figures(g, g['path'] + '/') + '</section>' for g in entries)
    buttons = '<button class="active" data-filter="all">全部</button>' + ''.join(
        f'<button data-filter="{esc(model)}">{esc(model)}</button>' for model in sorted({g['model'] for g in groups}))
    body = '<header><h1>AI 食物人脸拼贴 · 结果总览</h1><p>按模型、推理强度和编号整理。点击图片查看原图，展开文字查看解释。</p>'
    body += f'<p class="meta">正式结果：{len(formal)} 组，{sum(len(g["portraits"]) for g in formal)} 张最终图。</p><nav>{buttons}</nav></header>'
    body += cards(formal) + '<details><summary>早期已完成作品</summary>' + cards(early) + '</details>'
    body += '<script>document.querySelectorAll("[data-filter]").forEach(b=>b.onclick=()=>{document.querySelectorAll("[data-filter]").forEach(x=>x.classList.toggle("active",x===b));document.querySelectorAll("[data-model]").forEach(x=>x.hidden=b.dataset.filter!=="all"&&x.dataset.model!==b.dataset.filter)})</script>'
    (root / 'index.html').write_text(page('AI collage results', body), encoding='utf-8')
    (root / 'README.txt').write_text('Open index.html to browse final images.\nFolders: model_reasoning_number.\nFinal portrait PNGs are at the top level; records/ preserves all original attempts, explanations, and token usage.\nIncomplete portraits are not shown as duplicate or placeholder images.\n', encoding='utf-8')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--group', required=True)
    parser.add_argument('--move', action='store_true', help='Remove imported source only after hash verification')
    parser.add_argument('sources', type=Path, nargs='+')
    args = parser.parse_args()
    for source in args.sources:
        settings = read(source / 'experiment.json')['settings']
        if not (args.root / args.group).exists():
            group = reserve_group(args.root, settings['model'], settings['reasoning'])
            if group.name != args.group:
                raise ValueError(f'Next available result group is {group.name}')
        else:
            group = reserve_group(args.root, settings['model'], settings['reasoning'], args.group)
        register_experiment(group, source, move=args.move)
    print(group)

STYLE = '''body{font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f3f1eb;color:#24282d;margin:0}main{max-width:1160px;margin:auto;padding:32px 24px}h1{font-size:30px;margin:0 0 8px}h2{font-size:21px;margin:0}p{margin:8px 0 18px}a{color:#255955}header{margin-bottom:26px}.card{background:white;border:1px solid #dddcd4;border-radius:14px;padding:22px;margin:20px 0}.pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}figure{margin:16px 0 0}img{display:block;width:100%;height:420px;object-fit:contain;background:#eceae4;border-radius:7px}figcaption{margin-top:10px;font-weight:600}.meta{font-size:14px;color:#646765}.missing{height:420px;display:flex;align-items:center;justify-content:center;background:#f5f3ef;color:#777;border:1px dashed #bbb;border-radius:7px}details{margin-top:12px}pre{white-space:pre-wrap;font:14px/1.7 inherit}nav{display:flex;gap:10px;flex-wrap:wrap}button{padding:8px 16px;background:white;border:1px solid #bbb;border-radius:20px;cursor:pointer}button.active{background:#255955;color:white;border-color:#255955}.badge{font-size:13px;color:#805e25}footer{padding:20px 0;color:#777;font-size:13px}@media(max-width:700px){.pair{grid-template-columns:1fr}img,.missing{height:360px}main{padding:20px 12px}}'''

if __name__ == '__main__':
    main()
