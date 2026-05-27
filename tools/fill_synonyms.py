#!/usr/bin/env python3
import concurrent.futures
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path("/Users/bunkaji/Projects/ielts-vocab")
INDEX = ROOT / "index.html"
VOCAB_JSON = ROOT / "vocab-words.json"
CACHE = ROOT / "tools" / "datamuse_synonym_cache.json"
USER_AGENT = "ielts-vocab-personal-study/1.0 (https://github.com/cazy06/ielts-vocab)"


def js_unescape(value: str) -> str:
    return bytes(value, "utf-8").decode("unicode_escape")


def js_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def extract_words(source: str):
    pattern = re.compile(
        r'\{id:(\d+),w:"((?:\\.|[^"\\])*)",m:"((?:\\.|[^"\\])*)"'
        r'(?:,s:"((?:\\.|[^"\\])*)")?,et:"((?:\\.|[^"\\])*)",e:'
    )
    words = []
    for match in pattern.finditer(source):
        words.append({
            "id": int(match.group(1)),
            "w": js_unescape(match.group(2)),
            "s": js_unescape(match.group(4) or ""),
        })
    return words


def fetch_synonyms(word: str) -> str:
    query = urllib.parse.urlencode({"rel_syn": word, "max": "8"})
    url = f"https://api.datamuse.com/words?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as res:
        data = json.loads(res.read().decode("utf-8"))
    seen = set()
    synonyms = []
    normalized_word = word.lower().replace(" ", "")
    for item in data:
        candidate = str(item.get("word", "")).strip()
        if not candidate:
            continue
        compact = candidate.lower().replace(" ", "").replace("-", "")
        if compact == normalized_word or compact in seen:
            continue
        seen.add(compact)
        synonyms.append(candidate)
        if len(synonyms) >= 4:
            break
    return ", ".join(synonyms)


def replace_synonyms(source: str, synonyms_by_id: dict[int, str]) -> str:
    pattern = re.compile(
        r'(\{id:(\d+),w:"(?:\\.|[^"\\])*",m:"(?:\\.|[^"\\])*")'
        r'(?:,s:"(?:\\.|[^"\\])*")?,et:'
    )

    def repl(match):
        word_id = int(match.group(2))
        synonym = js_escape(synonyms_by_id.get(word_id, ""))
        return f'{match.group(1)},s:"{synonym}",et:'

    return pattern.sub(repl, source)


def update_vocab_json(synonyms_by_word: dict[str, str]):
    data = json.loads(VOCAB_JSON.read_text())
    for item in data:
        item["s"] = synonyms_by_word.get(item.get("w", ""), item.get("s", ""))
    VOCAB_JSON.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main():
    source = INDEX.read_text()
    words = extract_words(source)
    CACHE.parent.mkdir(exist_ok=True)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    pending = [item for item in words if item["w"] not in cache]
    print(f"words={len(words)} cached={len(cache)} pending={len(pending)}")

    def worker(item):
        word = item["w"]
        try:
            return word, fetch_synonyms(word)
        except Exception:
            return word, ""

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker, item) for item in pending]
        for future in concurrent.futures.as_completed(futures):
            word, synonyms = future.result()
            cache[word] = synonyms
            done += 1
            if done % 50 == 0 or done == len(pending):
                CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True))
                print(f"fetched {done}/{len(pending)}")
            time.sleep(0.01)

    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True))
    synonyms_by_id = {item["id"]: cache.get(item["w"], "") for item in words}
    synonyms_by_word = {item["w"]: cache.get(item["w"], "") for item in words}
    INDEX.write_text(replace_synonyms(source, synonyms_by_id))
    update_vocab_json(synonyms_by_word)
    filled = sum(1 for item in words if cache.get(item["w"], ""))
    print(f"filled={filled}/{len(words)}")


if __name__ == "__main__":
    main()
