#!/usr/bin/env python3
"""把 GoldenDict 词典（Babylon .bgl / StarDict）转换为 FoDict 的 fodict.dat。

FoDict 的 .dat 容器格式（与 App `lib/dictionary/fodict_service.dart` 对齐）：

    offset 0   : 16 字节 magic "fodict v1" (UTF-16LE)
    offset 16  : u32 version = 1
    offset 20  : u32 headerSize = 64
    offset 24  : u32 idxStart   = 64   (无内嵌索引)
    offset 28  : u32 contentStart = 64
    offset 32  : u32 contentStart = 64
    offset 64  : 重复 [kwLen u32][keyword UTF-16LE][defLen u32][definition UTF-16LE]

Babylon .bgl 解析（参考格式公开资料与 pyglossary 的格式说明）：
    - magic 12 34 00 01 / 12 34 00 02
    - offset 4..6 大端 u16 = gzip 起点
    - gzip 解压后是一串 block：
          byte -> type = b & 0xF, L = b >> 4
          L < 4  : 再读 L+1 字节大端 = block.data 长度
          L >= 4 : block.data 长度 = L - 4
      type 0   : 元信息
      type 2   : 内嵌资源（图片/HTML）
      type 3   : 字典元数据（标题/作者/授权…）
      type 10  : [1B 词长][词][2B 释文长][释文][可选 1B 别名长 + 别名 …]
      type 11  : [5B 词长][词][4B 别名数][4B 别名长 + 别名 …][4B 释文长][释文]

StarDict 解析：.ifo / .idx / .dict(.dz) / .syn。

用法：
    python3 tools/goldendict_to_fodict.py \
        --src ../GoldenDict/13Dicts --out ../goldendict_dat
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import io
import json
import os
import re
import struct
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------- 词典映射

DICTIONARIES = {
    'babylon-Abhisamacarika.ddbc.bgl': {
        'id': '029.ddbc-abhisamacarika',
        'name': 'Abhisamācārikā Dharmāḥ（大眾部律典詞彙）',
        'vendor': '法鼓文理學院 DILA / DDBC',
        'language': '梵文/英文',
        'category': '辞典/语言/D.梵巴藏英',
    },
    'babylon-dingfubao.dila.bgl': {
        'id': '030.dila-dingfubao',
        'name': '丁福保佛學大辭典（DILA 版）',
        'vendor': '法鼓文理學院 DILA',
        'language': '中文',
        'category': '辞典/中文/A.现代综合辞典',
        'note': '与 001.dfb-j 内容重复',
    },
    'babylon-hopkins.ddbc.bgl': {
        'id': '031.ddbc-hopkins',
        'name': '藏梵英佛學辭典（Hopkins）',
        'vendor': '法鼓文理學院 DILA / DDBC',
        'language': '藏文/梵文/英文',
        'category': '辞典/语言/D.梵巴藏英',
    },
    'babylon-kumarajiva.ddbc.bgl': {
        'id': '032.ddbc-kumarajiva',
        'name': '妙法蓮華經詞典（鳩摩羅什譯）',
        'vendor': '法鼓文理學院 DILA / DDBC',
        'language': '梵文/中文/英文',
        'category': '辞典/语言/D.梵巴藏英',
    },
    'babylon-lokaksema.ddbc.bgl': {
        'id': '033.ddbc-lokaksema',
        'name': '道行般若經詞典',
        'vendor': '法鼓文理學院 DILA / DDBC',
        'language': '梵文/中文/英文',
        'category': '辞典/语言/D.梵巴藏英',
    },
    'babylon-pali-chin.ddbc.bgl': {
        'id': '034.ddbc-pali-chin',
        'name': '巴漢辭典（Buddhadatta）',
        'vendor': '法鼓文理學院 DILA / DDBC',
        'language': '巴利文/中文',
        'category': '辞典/语言/D.梵巴藏英',
    },
    'babylon-tibskrit.ddbc.bgl': {
        'id': '035.ddbc-tibskrit',
        'name': 'Tibskrit 藏梵佛學詞彙',
        'vendor': '法鼓文理學院 DILA / DDBC',
        'language': '藏文/梵文/英文',
        'category': '辞典/语言/D.梵巴藏英',
    },
    'dharmaraksa.ddbc.bgl': {
        'id': '036.ddbc-dharmaraksa',
        'name': '正法華經詞典',
        'vendor': '法鼓文理學院 DILA / DDBC',
        'language': '梵文/中文/英文',
        'category': '辞典/语言/D.梵巴藏英',
    },
    'dzdl.bgl': {
        'id': '037.dzdl',
        'name': '大智度論辭典',
        'vendor': '李清順（如清）',
        'language': '中文',
        'category': '辞典/中文/C.其它现代辞典',
    },
    'stardict-ddbc.mahavyutpatti': {
        'id': '038.ddbc-mahavyutpatti',
        'name': '翻譯名義大集（Mahāvyutpatti）',
        'vendor': '法鼓文理學院 DILA / DDBC',
        'language': '梵文/藏文/中文',
        'category': '辞典/语言/D.梵巴藏英',
    },
    'stardict-ddbc.nanshanlu': {
        'id': '039.ddbc-nanshanlu',
        'name': '南山律學辭典（DDBC 版）',
        'vendor': '法鼓文理學院 DILA / DDBC',
        'language': '中文',
        'category': '辞典/中文/C.其它现代辞典',
        'note': '与 025.nanshanlv-j 内容重复',
    },
    'stardict-ddbc.soothill-hodous': {
        'id': '040.ddbc-soothill-hodous',
        'name': '漢英梵佛學詞典（Soothill-Hodous）',
        'vendor': '法鼓文理學院 DILA / DDBC',
        'language': '中文/英文/梵文',
        'category': '辞典/语言/D.梵巴藏英',
    },
    'stardict-pentaglot.ddbc': {
        'id': '041.ddbc-pentaglot',
        'name': '五譯合璧集要（Pentaglot）',
        'vendor': '法鼓文理學院 DILA / DDBC',
        'language': '梵文/藏文/中文/蒙古文/滿文',
        'category': '辞典/语言/D.梵巴藏英',
    },
}

# ---------------------------------------------------------------- 文本清洗

RE_TAG = re.compile(r'<[^>]+>')
RE_BR = re.compile(r'<\s*br\s*/?\s*>', re.IGNORECASE)
RE_P_END = re.compile(r'</\s*p\s*>', re.IGNORECASE)
RE_LI = re.compile(r'<\s*li[^>]*>', re.IGNORECASE)
RE_IMG = re.compile(r'<\s*img[^>]*>', re.IGNORECASE)
RE_A = re.compile(
    r'<\s*a\b[^>]*href\s*=\s*["\']?([^"\'>\s]+)["\']?[^>]*>(.*?)</\s*a\s*>',
    re.IGNORECASE | re.DOTALL,
)
RE_CHARSET = re.compile(r"<\s*charset\b[^>]*>", re.IGNORECASE)


class CleanStats:
    def __init__(self) -> None:
        self.links = 0
        self.images = 0
        self.charset_tags = 0
        self.long_keys = 0
        self.empty_defs = 0

    def merge(self, other: 'CleanStats') -> None:
        self.links += other.links
        self.images += other.images
        self.charset_tags += other.charset_tags
        self.long_keys += other.long_keys
        self.empty_defs += other.empty_defs


def clean_text(text: str, stats: CleanStats) -> str:
    """把 Babylon / StarDict 的 HTML 片段压成纯文本。"""
    if not text:
        return ''

    def _link(match: re.Match[str]) -> str:
        stats.links += 1
        href = match.group(1)
        label = match.group(2) or ''
        label = RE_TAG.sub('', label).strip()
        if not label:
            label = href
        if href.lower().startswith('bword://'):
            target = href[len('bword://'):]
            if target and target != label:
                return f'{label}【參見：{target}】'
        return label

    text = RE_A.sub(_link, text)
    stats.images += len(RE_IMG.findall(text))
    text = RE_IMG.sub('', text)
    stats.charset_tags += len(RE_CHARSET.findall(text))
    text = RE_CHARSET.sub('', text)
    text = RE_BR.sub('\n', text)
    text = RE_P_END.sub('\n', text)
    text = RE_LI.sub('• ', text)
    text = RE_TAG.sub('', text)
    text = html.unescape(text)
    text = text.replace('\xa0', ' ').replace('\u3000', ' ')
    text = text.replace('\x00', '').replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ---------------------------------------------------------------- .dat 写入

def encode_key(key: str, stats: CleanStats) -> bytes:
    if len(key) > 500:
        stats.long_keys += 1
        key = key[:500]
    return key.encode('utf-16le', 'replace')


def write_dat(path: str, entries: list[tuple[str, str]], stats: CleanStats) -> int:
    header = bytearray(64)
    header[0:18] = 'fodict v1'.encode('utf-16le')
    struct.pack_into('<I', header, 16, 1)
    struct.pack_into('<I', header, 20, 64)
    struct.pack_into('<I', header, 24, 64)
    struct.pack_into('<I', header, 28, 64)
    struct.pack_into('<I', header, 32, 64)

    written = 0
    with open(path, 'wb') as fh:
        fh.write(header)
        for key, definition in entries:
            if not key:
                continue
            if not definition:
                stats.empty_defs += 1
            kb = encode_key(key, stats)
            vb = definition.encode('utf-16le', 'replace')
            if len(vb) > 1_000_000:
                vb = vb[:1_000_000]
            fh.write(struct.pack('<I', len(kb)))
            fh.write(kb)
            fh.write(struct.pack('<I', len(vb)))
            fh.write(vb)
            written += 1
    return written


# ---------------------------------------------------------------- BGL 读取

def _uvar(data: bytes) -> int:
    return int.from_bytes(data, 'big')


def _bgl_blocks(payload: bytes):
    stream = io.BytesIO(payload)
    while True:
        first = stream.read(1)
        if not first:
            return
        value = first[0]
        block_type = value & 0xF
        length = value >> 4
        if length < 4:
            length = _uvar(stream.read(length + 1))
        else:
            length -= 4
        if length < 0:
            return
        chunk = stream.read(length) if length else b''
        if len(chunk) != length:
            return
        yield block_type, chunk


def _pick_encoding(samples: list[bytes]) -> str:
    candidates = ['utf-8', 'gb18030', 'big5', 'utf-16le']
    blob = [s for s in samples if s][:400]
    best = 'utf-8'
    best_ratio = -1.0
    for enc in candidates:
        ok = 0
        for item in blob:
            try:
                text = item.decode(enc)
            except UnicodeDecodeError:
                continue
            if not text:
                continue
            good = sum(
                1 for ch in text
                if ch.isprintable() or ch in '\r\n\t'
            )
            if good / len(text) > 0.95:
                ok += 1
        ratio = ok / max(1, len(blob))
        if ratio > best_ratio:
            best_ratio, best = ratio, enc
    return best


def read_bgl(path: str) -> tuple[list[tuple[str, str]], dict, dict]:
    raw = open(path, 'rb').read()
    if raw[:4] not in (b'\x12\x34\x00\x01', b'\x12\x34\x00\x02'):
        raise ValueError('不是 Babylon BGL 文件')
    gzip_offset = _uvar(raw[4:6])
    payload = gzip.decompress(raw[gzip_offset:])

    raw_entries: list[tuple[bytes, bytes, list[bytes]]] = []
    meta: dict[str, str] = {}
    resources = 0

    for block_type, data in _bgl_blocks(payload):
        if block_type == 2:
            resources += 1
            continue
        if block_type == 3 and len(data) >= 2:
            code = _uvar(data[:2])
            value = data[2:]
            key = {1: 'title', 2: 'author', 3: 'email', 4: 'license',
                   9: 'description'}.get(code)
            if key:
                for enc in ('utf-8', 'gb18030', 'big5'):
                    try:
                        meta[key] = value.decode(enc).strip('\x00').strip()
                        break
                    except UnicodeDecodeError:
                        continue
            continue
        if block_type == 11:
            pos = 0
            word_len = _uvar(data[pos:pos + 5])
            pos += 5
            word = data[pos:pos + word_len]
            pos += word_len
            alts_count = _uvar(data[pos:pos + 4])
            pos += 4
            alts = []
            for _ in range(alts_count):
                alt_len = _uvar(data[pos:pos + 4])
                pos += 4
                alts.append(data[pos:pos + alt_len])
                pos += alt_len
            defi_len = _uvar(data[pos:pos + 4])
            pos += 4
            raw_entries.append((word, data[pos:pos + defi_len], alts))
            continue
        if block_type in (1, 7, 10, 13):
            pos = 0
            word_len = data[pos]
            pos += 1
            word = data[pos:pos + word_len]
            pos += word_len
            defi_len = _uvar(data[pos:pos + 2])
            pos += 2
            definition = data[pos:pos + defi_len]
            pos += defi_len
            alts = []
            while pos < len(data):
                alt_len = data[pos]
                pos += 1
                alts.append(data[pos:pos + alt_len])
                pos += alt_len
            raw_entries.append((word, definition, alts))

    encoding = _pick_encoding(
        [w for w, _, _ in raw_entries[:200]] + [d for _, d, _ in raw_entries[:200]]
    )
    meta['encoding'] = encoding
    meta['resources'] = str(resources)

    entries: list[tuple[str, str]] = []
    for word, definition, alts in raw_entries:
        key = word.decode(encoding, 'replace').strip()
        definition = definition.decode(encoding, 'replace')
        entries.append((key, definition))
        for alt in alts:
            entries.append((alt.decode(encoding, 'replace').strip(), definition))
    return entries, meta, {'blocks': len(raw_entries), 'resources': resources}


# ---------------------------------------------------------------- StarDict

def read_stardict(directory: str, with_synonyms: bool = False) -> tuple[list[tuple[str, str]], dict, dict]:
    base = None
    ifo = None
    for name in sorted(os.listdir(directory)):
        if name.endswith('.ifo'):
            ifo = os.path.join(directory, name)
            base = ifo[:-4]
            break
    if not ifo:
        raise ValueError('目录中缺少 .ifo')

    info: dict[str, str] = {}
    with open(ifo, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if '=' in line:
                key, value = line.rstrip('\n').split('=', 1)
                info[key.strip()] = value.strip()

    idx_path = base + '.idx'
    dict_path = base + '.dict'
    if not os.path.exists(dict_path) and os.path.exists(dict_path + '.dz'):
        dict_path = dict_path + '.dz'
    syn_path = base + '.syn'

    idx = open(idx_path, 'rb').read()
    raw_dict = open(dict_path, 'rb').read()
    if dict_path.endswith('.dz'):
        raw_dict = gzip.decompress(raw_dict)

    seq = info.get('sametypesequence', '')
    records: list[tuple[str, bytes]] = []
    pos = 0
    while pos < len(idx):
        end = idx.find(b'\x00', pos)
        if end < 0:
            break
        word = idx[pos:end].decode('utf-8', 'replace')
        pos = end + 1
        offset, size = struct.unpack_from('>II', idx, pos)
        pos += 8
        records.append((word, raw_dict[offset:offset + size]))

    syns: list[tuple[str, int]] = []
    if os.path.exists(syn_path):
        syn = open(syn_path, 'rb').read()
        pos = 0
        while pos < len(syn):
            end = syn.find(b'\x00', pos)
            if end < 0:
                break
            alias = syn[pos:end].decode('utf-8', 'replace')
            pos = end + 1
            (index,) = struct.unpack_from('>I', syn, pos)
            pos += 4
            syns.append((alias, index))

    def parse_block(block: bytes) -> str:
        parts: list[str] = []
        if seq:
            types = seq
            i = 0
            for n, type_char in enumerate(types):
                last = n == len(types) - 1
                if type_char.islower():
                    if last:
                        chunk = block[i:]
                        i = len(block)
                    else:
                        end = block.find(b'\x00', i)
                        if end < 0:
                            break
                        chunk = block[i:end]
                        i = end + 1
                else:
                    if last:
                        chunk = block[i:]
                        i = len(block)
                    else:
                        if i + 4 > len(block):
                            break
                        (size,) = struct.unpack_from('>I', block, i)
                        i += 4
                        chunk = block[i:i + size]
                        i += size
                if type_char.lower() in ('g', 'm', 'x', 'h', 't', 'y', 'k'):
                    parts.append(chunk.decode('utf-8', 'replace'))
        else:
            i = 0
            while i < len(block):
                type_char = chr(block[i])
                i += 1
                if type_char.islower():
                    end = block.find(b'\x00', i)
                    if end < 0:
                        break
                    chunk = block[i:end]
                    i = end + 1
                else:
                    if i + 4 > len(block):
                        break
                    (size,) = struct.unpack_from('>I', block, i)
                    i += 4
                    chunk = block[i:i + size]
                    i += size
                if type_char.lower() in ('g', 'm', 'x', 'h', 't', 'y', 'k'):
                    parts.append(chunk.decode('utf-8', 'replace'))
        return '\n'.join(part for part in parts if part.strip())

    entries: list[tuple[str, str]] = []
    for word, block in records:
        entries.append((word, parse_block(block)))
    used_synonyms = 0
    if with_synonyms:
        for alias, index in syns:
            if 0 <= index < len(records):
                entries.append((alias, entries[index][1]))
                used_synonyms += 1

    meta = {k: v for k, v in info.items() if v}
    return entries, meta, {
        'records': len(records),
        'synonyms': len(syns),
        'synonyms_used': used_synonyms,
        'resources': 0,
    }


# ---------------------------------------------------------------- ini

def _source_sha256(source: str) -> str:
    digest = hashlib.sha256()
    if os.path.isdir(source):
        for name in sorted(os.listdir(source)):
            path = os.path.join(source, name)
            if os.path.isfile(path):
                digest.update(name.encode('utf-8'))
                with open(path, 'rb') as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b''):
                        digest.update(chunk)
        return digest.hexdigest()
    with open(source, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_ini(ini_path: str, dat_path: str, cfg: dict, meta: dict, counts: dict,
              source: str) -> None:
    sha = _source_sha256(source)
    lines = [
        '# 由 goldendict_to_fodict.py 自动生成',
        f'name={cfg["name"]}',
        f'vendor={cfg["vendor"]}',
        f'language={cfg["language"]}',
        f'category={cfg["category"]}',
        'version=1',
        '',
        '[statistics]',
        f'entry_count = {counts["entries"]}',
        f'dat_size = {os.path.getsize(dat_path)} bytes',
        '',
        '[source]',
        f'file = {os.path.basename(source)}',
        f'format = {cfg["format"]}',
        f'sha256 = {sha}',
    ]
    for key in ('title', 'author', 'email', 'license', 'description',
                'bookname', 'website', 'date', 'encoding'):
        value = meta.get(key)
        if value:
            value = str(value).replace('\n', ' ').strip()
            lines.append(f'{key} = {value[:800]}')
    lines.append('')
    lines.append('[conversion]')
    lines.append(f'converted_at = {datetime.now(timezone.utc).replace(microsecond=0).isoformat()}')
    lines.append('converter = goldendict_to_fodict.py')
    lines.append('text_only = true')
    lines.append(f'lost_links = {counts["links"]}')
    lines.append(f'lost_images = {counts["images"]}')
    lines.append(f'dropped_resources = {counts["resources"]}')
    lines.append(f'dropped_metadata_prefix_keys = {counts["metadata_keys"]}')
    lines.append(f'skipped_empty_entries = {counts.get("skipped_empty", 0)}')
    lines.append(f'merged_duplicate_keys = {counts.get("duplicates", 0)}')
    lines.append('')
    with open(ini_path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))


# ---------------------------------------------------------------- 主流程

def convert_one(src: str, out_dir: str, with_synonyms: bool = False) -> dict:
    name = os.path.basename(src)
    cfg = DICTIONARIES[name]
    stats = CleanStats()

    if name.endswith('.bgl'):
        cfg['format'] = 'babylon-bgl'
        raw_entries, meta, counts = read_bgl(src)
    else:
        cfg['format'] = 'stardict'
        raw_entries, meta, counts = read_stardict(src, with_synonyms)
        counts['metadata_keys'] = 0

    merged: dict[str, str] = {}
    order: list[str] = []
    duplicates = 0
    metadata_keys = 0
    skipped_empty = 0
    for key, definition in raw_entries:
        key = key.strip()
        if not key:
            continue
        if key.startswith('#') and cfg['format'] == 'babylon-bgl':
            metadata_keys += 1
            continue
        definition = clean_text(definition, stats)
        if not definition:
            skipped_empty += 1
            continue
        if key in merged:
            duplicates += 1
            if merged[key] != definition:
                merged[key] = merged[key] + '\n' + definition
            continue
        merged[key] = definition
        order.append(key)

    entries = [(key, merged[key]) for key in order]

    target = os.path.join(out_dir, cfg['id'])
    os.makedirs(target, exist_ok=True)
    dat_path = os.path.join(target, 'fodict.dat')
    written = write_dat(dat_path, entries, stats)
    counts.update({
        'entries': written,
        'duplicates': duplicates,
        'skipped_empty': skipped_empty,
        'metadata_keys': metadata_keys,
        'links': stats.links,
        'images': stats.images,
        'charset_tags': stats.charset_tags,
        'long_keys': stats.long_keys,
        'empty_defs': stats.empty_defs,
        'dat_size': os.path.getsize(dat_path),
    })
    write_ini(os.path.join(target, 'fodict.ini'), dat_path, cfg, meta, counts, src)

    # 回读自检：按 App 的解析方式统计
    verify = verify_dat(dat_path)
    counts['verify_entries'] = verify
    ok = verify == written
    print(
        f'{"OK " if ok else "BAD"} {cfg["id"]:26} entries={written:6d} '
        f'dat={counts["dat_size"] / 1048576:6.2f}MB dup={duplicates:4d} '
        f'links={stats.links:6d} img={stats.images:4d} res={counts["resources"]:4d}'
    )
    return {'id': cfg['id'], 'name': cfg['name'], 'ok': ok, **counts}


def verify_dat(path: str) -> int:
    data = open(path, 'rb').read()
    if len(data) < 64:
        return 0
    (content_start,) = struct.unpack_from('<I', data, 32)
    pos = content_start
    count = 0
    while pos + 8 <= len(data):
        (kw_len,) = struct.unpack_from('<I', data, pos)
        if kw_len <= 0 or kw_len > 1000 or pos + 4 + kw_len > len(data):
            break
        pos += 4 + kw_len
        (def_len,) = struct.unpack_from('<I', data, pos)
        pos += 4
        if def_len <= 0 or pos + def_len > len(data):
            break
        pos += def_len
        count += 1
    return count


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    parser = argparse.ArgumentParser(description='GoldenDict -> fodict.dat')
    parser.add_argument('--src', default=os.path.join(ROOT_DIR, 'GoldenDict', '13Dicts'))
    parser.add_argument('--out', default=os.path.join(ROOT_DIR, 'goldendict_dat'))
    parser.add_argument('--only', action='append', default=[],
                        help='只转换指定源名（可多次）')
    parser.add_argument('--synonyms', action='store_true',
                        help='把 StarDict .syn 别名也写成独立词条（体积会膨胀数倍）')
    args = parser.parse_args()

    src_dir = os.path.abspath(args.src)
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    results = []
    for name in sorted(DICTIONARIES):
        if args.only and name not in args.only:
            continue
        src = os.path.join(src_dir, name)
        if not os.path.exists(src) or (os.path.isdir(src) and not os.listdir(src)):
            print(f'SKIP {name}（不存在或为空）')
            continue
        try:
            results.append(convert_one(src, out_dir, args.synonyms))
        except Exception as error:  # noqa: BLE001
            print(f'FAIL {name}: {error}', file=sys.stderr)
            results.append({'id': DICTIONARIES[name]['id'], 'ok': False,
                            'error': str(error)})

    report = os.path.join(out_dir, 'conversion_report.json')
    with open(report, 'w', encoding='utf-8') as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    total = sum(item.get('entries', 0) for item in results)
    size = sum(item.get('dat_size', 0) for item in results)
    print(f'\n共 {len(results)} 部，{total} 条，{size / 1048576:.2f} MB -> {out_dir}')
    print(f'报告：{report}')
    return 0 if all(item.get('ok') for item in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
