#!/usr/bin/env python3
import concurrent.futures
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path("/Users/bunkaji/Projects/ielts-vocab")
INDEX = ROOT / "index.html"
CACHE = ROOT / "tools" / "wiktionary_etymology_cache.json"
USER_AGENT = "ielts-vocab-personal-study/1.0 (https://github.com/cazy06/ielts-vocab)"

LANG_MAP = {
    "Middle English": "中英語",
    "Old English": "古英語",
    "Modern English": "現代英語",
    "Old French": "古フランス語",
    "Middle French": "中期フランス語",
    "French": "フランス語",
    "Anglo-Norman": "アングロノルマン語",
    "Latin": "ラテン語",
    "Late Latin": "後期ラテン語",
    "Medieval Latin": "中世ラテン語",
    "Vulgar Latin": "俗ラテン語",
    "Ancient Greek": "古代ギリシア語",
    "Greek": "ギリシア語",
    "Proto-Indo-European": "印欧祖語",
    "Proto-Germanic": "ゲルマン祖語",
    "Proto-West Germanic": "西ゲルマン祖語",
    "Old Norse": "古ノルド語",
    "German": "ドイツ語",
    "Dutch": "オランダ語",
    "Spanish": "スペイン語",
    "Italian": "イタリア語",
    "Arabic": "アラビア語",
    "Sanskrit": "サンスクリット語",
}


def extract_base_words(source: str):
    start = source.index("const BASE_WORDS=[")
    array_start = source.index("[", start)
    depth = 0
    quote = ""
    escape = False
    for i in range(array_start, len(source)):
        ch = source[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = ""
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return source[array_start : i + 1], array_start, i + 1
    raise RuntimeError("BASE_WORDS array not found")


def parse_objects(array_src: str):
    objects = []
    for obj in re.finditer(r"\{id:(\d+),w:\"((?:\\.|[^\"\\])*)\",m:\"((?:\\.|[^\"\\])*)\",et:\"((?:\\.|[^\"\\])*)\",e:", array_src):
        objects.append({"id": int(obj.group(1)), "w": bytes(obj.group(2), "utf-8").decode("unicode_escape")})
    return objects


def strip_tags(fragment: str) -> str:
    fragment = re.sub(r"<sup[^>]*>.*?</sup>", "", fragment, flags=re.S)
    fragment = re.sub(r"<style[^>]*>.*?</style>", "", fragment, flags=re.S)
    fragment = re.sub(r"<script[^>]*>.*?</script>", "", fragment, flags=re.S)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    text = html.unescape(fragment)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace(" ,", ",").replace(" .", ".")
    return text


def polish(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s*\(compare .+?\)", "", text, flags=re.I)
    text = re.sub(r"\s*Compare .+?(?:\.|$)", "", text, flags=re.I)
    text = re.sub(r"\s*Doublet of .+?(?:\.|$)", "", text, flags=re.I)
    for en, ja in sorted(LANG_MAP.items(), key=lambda x: -len(x[0])):
        text = re.sub(rf"\b{re.escape(en)}\b", ja, text)
    replacements = [
        (r"^Inherited from ", "継承: "),
        (r"^Borrowed from ", "借用: "),
        (r"^From ", "由来: "),
        (r"^Ultimately from ", "最終的に: "),
        (r"^Equivalent to ", "構成: "),
        (r" equivalent to ", " 構成: "),
        (r", from ", " ← "),
        (r" from ", " ← "),
        (r"\+ ", "+ "),
        (r"\.$", ""),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 170:
        text = text[:167].rstrip(" ,;") + "..."
    return text


def fetch_etymology(word: str) -> str:
    page = urllib.parse.quote(word.replace(" ", "_"))
    url = f"https://en.wiktionary.org/w/api.php?action=parse&page={page}&prop=text&format=json&formatversion=2"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as res:
        data = json.loads(res.read().decode("utf-8"))
    if "parse" not in data or "text" not in data["parse"]:
        return ""
    rendered = data["parse"]["text"]
    english_match = re.search(r'<h2 id="English">English</h2>', rendered)
    if english_match:
        rendered = rendered[english_match.start() :]
    next_lang = re.search(r'<h2 id="[^"]+">', rendered[english_match.end() if english_match else 1 :])
    if english_match and next_lang:
        rendered = rendered[: english_match.end() + next_lang.start()]

    parts = []
    for match in re.finditer(r'<h3 id="Etymology(?:_[0-9]+)?">Etymology(?: [0-9]+)?</h3>', rendered):
        start = match.end()
        nxt = re.search(r'<div class="mw-heading mw-heading[23]"><h[23] id="', rendered[start:])
        end = start + nxt.start() if nxt else len(rendered)
        chunk = rendered[start:end]
        para_match = re.search(r"<p>(.*?)</p>", chunk, flags=re.S)
        if para_match:
            text = polish(strip_tags(para_match.group(1)))
            if text:
                parts.append(text)
        if len(parts) >= 2:
            break
    return " / ".join(parts)


def js_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def replace_etymologies(source: str, et_by_id: dict[int, str]) -> str:
    def repl(match):
        word_id = int(match.group(1))
        et = js_escape(et_by_id.get(word_id, ""))
        return f'{match.group(1)}{match.group(2)},et:"{et}",e:'

    return re.sub(r'(\{id:(\d+),w:"(?:\\.|[^"\\])*",m:"(?:\\.|[^"\\])*"),et:"(?:\\.|[^"\\])*",e:', lambda m: f'{m.group(1)},et:"{js_escape(et_by_id.get(int(m.group(2)), ""))}",e:', source)


def main():
    source = INDEX.read_text()
    array_src, _, _ = extract_base_words(source)
    words = parse_objects(array_src)
    CACHE.parent.mkdir(exist_ok=True)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

    pending = [w for w in words if w["w"] not in cache]
    print(f"words={len(words)} cached={len(cache)} pending={len(pending)}")

    def worker(item):
        word = item["w"]
        try:
            return word, fetch_etymology(word)
        except Exception:
            return word, ""

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(worker, item) for item in pending]
        for future in concurrent.futures.as_completed(futures):
            word, et = future.result()
            cache[word] = et
            done += 1
            if done % 25 == 0 or done == len(pending):
                CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True))
                print(f"fetched {done}/{len(pending)}")
            time.sleep(0.02)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True))

    et_by_id = {w["id"]: cache.get(w["w"], "") for w in words}
    updated = replace_etymologies(source, et_by_id)
    INDEX.write_text(updated)
    filled = sum(1 for w in words if cache.get(w["w"], ""))
    print(f"filled={filled}/{len(words)}")


if __name__ == "__main__":
    main()
