## 结果

```bash
cd cbeta-fodict
python3 tools/goldendict_to_fodict.py                 # 全部 13 部
python3 tools/goldendict_to_fodict.py --only dzdl.bgl # 单部
python3 tools/goldendict_to_fodict.py --synonyms      # StarDict 别名也写成词条（体积数倍）
```

输出：`cbeta-fodict/goldendict_dat/<id>/fodict.dat` + `fodict.ini`，外加 `conversion_report.json`。

| id | 词条 | .dat | 合并重复 | 链接 | 图片 | 丢弃资源 | 未用同义词 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 029.ddbc-abhisamacarika | 3,488 | 3.17 MB | 5 | 0 | 0 | 0 | 0 |
| 030.dila-dingfubao | 31,366 | 5.70 MB | 0 | 7,428 | 934 | 157 | 0 |
| 031.ddbc-hopkins | 18,382 | 6.27 MB | 59 | 0 | 0 | 0 | 0 |
| 032.ddbc-kumarajiva | 2,419 | 1.51 MB | 177 | 20,637 | 0 | 0 | 0 |
| 033.ddbc-lokaksema | 1,791 | 3.26 MB | 148 | 1,661 | 0 | 0 | 0 |
| 034.ddbc-pali-chin | 10,530 | 0.87 MB | 69 | 0 | 0 | 0 | 0 |
| 035.ddbc-tibskrit | 10,471 | 9.95 MB | 13 | 25,135 | 0 | 0 | 0 |
| 036.ddbc-dharmaraksa | 3,408 | 1.85 MB | 34 | 25,450 | 0 | 0 | 0 |
| 037.dzdl | 3,613 | 2.67 MB | 1 | 10,007 | 659 | 549 | 0 |
| 038.ddbc-mahavyutpatti | 8,930 | 4.24 MB | 447 | 0 | 0 | 0 | 49,852 |
| 039.ddbc-nanshanlu | 3,218 | 2.31 MB | 0 | 0 | 0 | 0 | 13,084 |
| 040.ddbc-soothill-hodous | 16,689 | 3.76 MB | 103 | 0 | 0 | 0 | 0 |
| 041.ddbc-pentaglot | 1,056 | 0.39 MB | 0 | 0 | 0 | 0 | 0 |
| **合计** | **115,361** | **45.95 MB** | | **90,318** | **1,593** | **706** | **62,936** |

- 每部都用与 App `fodict_service.dart` 相同的逻辑回读自检，`entries == verify_entries` 全部通过。
- BGL 解析是自己实现的（magic → gzip offset → block 流 → type 10/11 词条），不依赖 pyglossary。

## 丢失了哪些信息

**1. 富文本排版（全丢）**
粗体/斜体/字体/字号/颜色/上下标/段落样式 → 只留纯文本与换行；表格被拍平成文字（dzdl 的图表尤其明显）。

**2. 图片与内嵌资源（全丢）**
- `<img>` 引用：`030` 934 处、`037` 659 处，已从正文删除。
- 内嵌资源块：`030` 157 个（png/pnfm）、`037` 549 个（jpg/jpfm），`fodict.dat` 没有资源槽位，直接丢弃。

**3. 超链接语义（共 90,318 处）**
Babylon `bword://` 交叉引用只保留锚文本，必要时追加 `【參見：目标】` 文字；**跳转、锚点、反向链接关系丢失**，无法点击。

**4. 词典元数据里的 HTML / 图标**
- `029` 的 `about.htm`（type3 code 65）、各词典 `.ico` 图标未保存。
- type 0/3 的二进制字段（语言码、字符集、内部 ID、block 统计等）未保留；只有 `title/author/email/license/description` 抄进了 `fodict.ini`。

**5. StarDict 同义词（默认丢失 62,936 条）**
`mahavyutpatti` 49,852、`nanshanlu` 13,084 条 `.syn` 别名默认不写入（会让体积膨胀约 5–7 倍）；需要时加 `--synonyms`。

**6. 同名词条被合并（共 1,356 条）**
同一 key 的多条释文用换行拼成一条（`mahavyutpatti` 447、`soothill` 103、`kumarajiva` 177…）。原始“同名词条各自独立”的边界丢失。

**7. 被丢弃的条目**
- 空释文：`tibskrit` 13、`pentaglot` 1（`defLen=0` 会让 App 的解析器提前终止，必须过滤）。
- 伪词条：`dingfubao` 1 条 `#bookname=…`。
- 无：超长 key（>500 字符）0 条。

**8. 文本规范化（不可逆的小改动）**
`&nbsp;`→空格、连续空行压缩、行尾空白清理、HTML 实体解码（`&apos;` 等）；原始换行/缩进无法 100% 还原。

**9. Babylon 私用字符表**
`<charset c=…>` 特殊字符：本批 0 次；若遇到会被直接删掉（脚本已计数）。

**10. 格式附带的检索特性**
没有拼音、模糊、词形归一化；搜索仍是 App 现有的子串匹配。BGL 的块顺序 / StarDict 的 idx 顺序被保留，但原始索引文件不再存在。

## 保留下来了

- 全部词条正文（115,361 条），编码/实体已正确还原。
- BGL 的 **alternates 别名**会写成独立词条（所以 `029` 是 3,488 而非 3,484）。
- 每部的 `name / vendor / language / category / title / author / email / license / description`、源文件 SHA256、丢失计数，全部记在 `fodict.ini`，便于核查与署名。

## 两个提醒

- `030.dila-dingfubao` ≈ `001.dfb-j`、`039.ddbc-nanshanlu` ≈ `025.nanshanlv-j`，内容重复，发布前建议二选一。
- 输出目录目前是未跟踪的 `goldendict_dat/`；下次打包时可复制进 `fodict/` 跑 `package_dictionaries.sh`，再补 `generate_manifest.py` 的 `NAMES` 和 App 的 `_dictionaryNames`。

Made changes.