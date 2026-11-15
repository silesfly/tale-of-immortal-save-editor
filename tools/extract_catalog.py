#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract compact offline Korean + Chinese catalog bundle to src/catalog-data.js."""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_URL_RE = re.compile(
    r'(?i)\b(?:https?|ftp|wss?)://|\b(?:src|href|action|poster|data|cite)\s*=\s*["\']?\s*//|\burl\(\s*["\']?\s*(?:https?|ftp|wss?)?//'
)
TAG_RE = re.compile(r"<[^>\n]{1,120}>")

PROPERTY_FIELDS = {
    "groups": {
        "core": [
            {"key": "d", "name": "gradeID", "kr": "경지", "min": 1, "max": 44},
            {"key": "s", "name": "exp", "kr": "수양 (경험치)", "min": 0, "max": 999999999},
            {"key": "y", "name": "age", "kr": "나이 (개월)", "min": 12, "max": 120000},
            {"key": "u", "name": "life", "kr": "수명 상한 (개월)", "min": 12, "max": 1200000},
            {"key": "i", "name": "beauty", "kr": "매력", "min": 0, "max": 9999},
            {"key": "k", "name": "talent", "kr": "오성", "min": 0, "max": 9999},
            {"key": "a", "name": "reputation", "kr": "명성", "min": 0, "max": 99999999},
            {"key": "j", "name": "abilityPoint", "kr": "도력", "min": 0, "max": 999999},
            {"key": "o", "name": "standUp", "kr": "정도 수치", "min": 0, "max": 99999},
            {"key": "p", "name": "standDown", "kr": "마도 수치", "min": 0, "max": 99999},
        ],
        "vital": [
            {"key": "x", "name": "hp", "kr": "현재 체력", "min": 1, "max": 99999999},
            {"key": "c", "name": "hpMax", "kr": "최대 체력", "min": 1, "max": 99999999},
            {"key": "v", "name": "mp", "kr": "현재 영력", "min": 0, "max": 99999999},
            {"key": "b", "name": "mpMax", "kr": "최대 영력", "min": 0, "max": 99999999},
            {"key": "n", "name": "sp", "kr": "현재 염력", "min": 0, "max": 99999999},
            {"key": "m", "name": "spMax", "kr": "최대 염력", "min": 0, "max": 99999999},
            {"key": "l", "name": "health", "kr": "현재 건강", "min": 0, "max": 99999},
            {"key": "z", "name": "healthMax", "kr": "최대 건강", "min": 1, "max": 99999},
            {"key": "5", "name": "energy", "kr": "현재 정력", "min": 0, "max": 99999},
            {"key": "6", "name": "energyMax", "kr": "최대 정력", "min": 1, "max": 99999},
            {"key": "qx", "name": "mood", "kr": "현재 기분", "min": 0, "max": 99999},
            {"key": "qc", "name": "moodMax", "kr": "최대 기분", "min": 1, "max": 99999},
        ],
        "combat": [
            {"key": "1", "name": "attack", "kr": "공격", "min": 0, "max": 99999999},
            {"key": "2", "name": "defense", "kr": "방어", "min": 0, "max": 99999999},
            {"key": "3", "name": "footSpeed", "kr": "각력", "min": 0, "max": 999999},
            {"key": "4", "name": "luck", "kr": "행운", "min": 0, "max": 99999},
            {"key": "7", "name": "crit", "kr": "회심", "min": 0, "max": 999999},
            {"key": "8", "name": "critValue", "kr": "회심배율", "min": 0, "max": 999999},
            {"key": "9", "name": "guard", "kr": "호심", "min": 0, "max": 999999},
            {"key": "qq", "name": "guardValue", "kr": "호심배율", "min": 0, "max": 999999},
            {"key": "qw", "name": "moveSpeed", "kr": "전투 이동속도", "min": 0, "max": 99999},
            {"key": "qe", "name": "phycicalFree", "kr": "물리면상", "min": 0, "max": 99999},
            {"key": "qr", "name": "magicFree", "kr": "마법면상", "min": 0, "max": 99999},
        ],
        "roots": [
            {"key": "qt", "name": "basisFire", "kr": "화영근 (火)", "min": 0, "max": 9999},
            {"key": "qy", "name": "basisFroze", "kr": "수영근 (水)", "min": 0, "max": 9999},
            {"key": "qu", "name": "basisThunder", "kr": "뇌영근 (雷)", "min": 0, "max": 9999},
            {"key": "qi", "name": "basisWind", "kr": "풍영근 (风)", "min": 0, "max": 9999},
            {"key": "qo", "name": "basisEarth", "kr": "토영근 (土)", "min": 0, "max": 9999},
            {"key": "qp", "name": "basisWood", "kr": "목영근 (木)", "min": 0, "max": 9999},
        ],
        "weapons": [
            {"key": "qa", "name": "basisSword", "kr": "검법 (剑)", "min": 0, "max": 9999},
            {"key": "qs", "name": "basisSpear", "kr": "창법 (枪)", "min": 0, "max": 9999},
            {"key": "qd", "name": "basisBlade", "kr": "도법 (刀)", "min": 0, "max": 9999},
            {"key": "qf", "name": "basisFist", "kr": "권법 (拳)", "min": 0, "max": 9999},
            {"key": "qg", "name": "basisPalm", "kr": "장법 (掌)", "min": 0, "max": 9999},
            {"key": "qh", "name": "basisFinger", "kr": "지법 (指)", "min": 0, "max": 9999},
        ],
        "artisans": [
            {"key": "qj", "name": "refineElixir", "kr": "연단 (炼丹)", "min": 0, "max": 9999},
            {"key": "qk", "name": "refineWeapon", "kr": "연기 (炼器)", "min": 0, "max": 9999},
            {"key": "ql", "name": "geomancy", "kr": "풍수 (风水)", "min": 0, "max": 9999},
            {"key": "qz", "name": "symbol", "kr": "화부 (画符)", "min": 0, "max": 9999},
            {"key": "wq", "name": "herbal", "kr": "약재 (药材)", "min": 0, "max": 9999},
            {"key": "ww", "name": "mine", "kr": "광재 (矿材)", "min": 0, "max": 9999},
        ],
    }
}


def clean(val) -> str:
    if val is None:
        return ""
    return " ".join(TAG_RE.sub("", str(val).replace("\ufeff", "")).split())


def trunc(val, limit: int) -> str:
    text = clean(val)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def load_json(path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"Required catalog input missing: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rows_of(data):
    if isinstance(data, dict):
        return list(data.values())
    return data if isinstance(data, list) else []


def to_int(val, default: int = 0) -> int:
    try:
        return int(str(val).strip()) if val not in (None, "") else default
    except ValueError:
        try:
            return int(float(str(val).strip()))
        except ValueError:
            return default


def build_catalog(data_dir: Path, corpus_dir=None) -> dict:
    lt = {}
    for r in rows_of(load_json(data_dir / "json/LocalText.json")):
        k = str(r.get("key") or "").strip()
        if k:
            lt[k] = (clean(r.get("kr") or r.get("ch")), clean(r.get("ch")))

    def lt_kr(k):
        if k in (None, "", "0"):
            return ""
        s = str(k).strip()
        return lt[s][0] if s in lt else ""

    def lt_ch(k):
        if k in (None, "", "0"):
            return ""
        s = str(k).strip()
        return lt[s][1] if s in lt else ""

    item_types = {}
    for r in rows_of(load_json(data_dir / "json/ItemType.json")):
        tid = str(r.get("id") or "").strip()
        if tid:
            lbl = lt_kr(r.get("name")) or lt_ch(r.get("name"))
            if lbl:
                item_types[tid] = lbl

    items = []
    for r in rows_of(load_json(data_dir / "json/ItemProps.json")):
        kr = lt_kr(r.get("name"))
        ch = lt_ch(r.get("name"))
        if not kr and not ch:
            continue
        typ = str(r.get("type") or "0").strip()
        cls = str(r.get("className") or "0").strip()
        items.append({
            "id": to_int(r.get("id")),
            "kr": kr or ch,
            "ch": ch,
            "type": to_int(typ),
            "cls": cls,
            "cat": item_types.get(cls) or item_types.get(typ) or "기타",
            "lv": to_int(r.get("level"), 1),
            "ov": 1 if str(r.get("isOverlay")) == "1" else 0,
            "worth": to_int(r.get("worth"), 0),
            "desc": trunc(lt_kr(r.get("desc")), 140),
        })
    items.sort(key=lambda x: x["id"])

    realms = []
    for r in rows_of(load_json(data_dir / "json/RoleGrade.json")):
        realms.append({
            "id": to_int(r.get("id")),
            "grade": to_int(r.get("grade")),
            "phase": to_int(r.get("phase")),
            "kr": f"{lt_kr(r.get('gradeName'))} {lt_kr(r.get('phaseName'))}".strip(),
            "ch": f"{lt_ch(r.get('gradeName'))}{lt_ch(r.get('phaseName'))}".strip(),
            "qualityKr": lt_kr(r.get("qualityName")),
            "exp": to_int(r.get("exp")),
        })
    realms.sort(key=lambda x: x["id"])

    destinies = []
    for r in rows_of(load_json(data_dir / "json/RoleCreateFeature.json")):
        kr = lt_kr(r.get("name"))
        ch = lt_ch(r.get("name"))
        if not kr and not ch:
            continue
        destinies.append({
            "id": to_int(r.get("id")),
            "type": to_int(r.get("type")),
            "lv": to_int(r.get("level")),
            "dur": to_int(r.get("duration"), -1),
            "kr": kr or ch,
            "ch": ch,
            "tips": trunc(lt_kr(r.get("tips")), 150),
        })
    destinies.sort(key=lambda x: x["id"])

    sprites = []
    for r in rows_of(load_json(data_dir / "parsed/artifact_sprites_32_complete.json")):
        bs = r.get("base_skill") or []
        sprites.append({
            "id": to_int(r.get("id")),
            "kr": clean(r.get("name_kr") or r.get("name")),
            "area": clean(r.get("area_kr") or r.get("area")),
            "lv": to_int(r.get("level"), 1),
            "likes": ", ".join(clean(x) for x in (r.get("likes_kr") or []) if clean(x)),
            "skill": clean(bs[0]) if bs else "",
        })
    sprites.sort(key=lambda x: x["id"])

    hearts = []
    for r in rows_of(load_json(data_dir / "parsed/taoist_hearts.json")):
        raw = r.get("raw") or {}
        hkey = raw.get("heartName") or r.get("name")
        dkey = raw.get("heartDescribe") or raw.get("tips")
        kr = lt_kr(hkey) or clean(r.get("name"))
        ch = lt_ch(hkey)
        desc = lt_kr(dkey) or clean(r.get("desc"))
        hearts.append({"id": to_int(r.get("id")), "kr": kr, "ch": ch, "desc": trunc(desc, 150)})
    hearts.sort(key=lambda x: x["id"])

    wingmen = []
    for r in rows_of(load_json(data_dir / "parsed/wingmen_11_scaled.json")):
        wingmen.append({
            "id": to_int(r.get("id")),
            "kr": clean(r.get("name")),
            "desc": trunc(r.get("effectDesc") or r.get("desc"), 150),
        })
    wingmen.sort(key=lambda x: x["id"])

    domains = [
        {
            "root": clean(r.get("root")),
            "stone": clean(r.get("stone")),
            "main_rule": trunc(r.get("main_rule"), 150),
            "sub_rule": trunc(r.get("sub_rule"), 150),
        }
        for r in rows_of(load_json(data_dir / "parsed/enlightenment_domains_12.json"))
    ]

    martial_names = {}
    for key, fn in (
        ("attack", "BattleSkillAttack.json"),
        ("ability", "BattleAbilityBase.json"),
        ("step", "BattleStepBase.json"),
    ):
        mp = {}
        p = data_dir / "json" / fn
        if p.is_file():
            for r in rows_of(load_json(p)):
                sid = str(r.get("id") or "").strip()
                nm = lt_kr(r.get("name")) or lt_ch(r.get("name"))
                if sid and nm:
                    mp[sid] = nm
        martial_names[key] = mp

    school_names = {}
    for r in rows_of(load_json(data_dir / "json/SchoolName.json")):
        sid = str(r.get("id") or "").strip()
        if sid:
            school_names[sid] = {"n1": lt_kr(r.get("name1")), "n2": lt_kr(r.get("name2"))}

    codex_entries, endgame_builds = [], []
    if corpus_dir and (corpus_dir / "codex-atlas.json").is_file():
        cdata = load_json(corpus_dir / "codex-atlas.json")
        for r in rows_of(cdata.get("entries") or [])[:120]:
            codex_entries.append({
                "category": clean(r.get("category")),
                "name_ko": clean(r.get("name_ko")),
                "tier": clean(r.get("tier")),
                "source": clean(r.get("source")),
                "effects": trunc(r.get("effects"), 140),
            })
        for b in rows_of(cdata.get("endgame_builds") or cdata.get("endgameBuilds") or [])[:30]:
            endgame_builds.append({
                "name": clean(b.get("name") or b.get("title") or b.get("build_ko")),
                "summary": trunc(b.get("summary") or b.get("core_synergy") or b.get("notes") or str(b), 160),
            })

    flat_props = {}
    for grp in PROPERTY_FIELDS["groups"].values():
        for entry in grp:
            flat_props[entry["key"]] = entry

    return {
        "version": "1.0",
        "items": items,
        "itemTypes": item_types,
        "realms": realms,
        "destinies": destinies,
        "sprites": sprites,
        "hearts": hearts,
        "wingmen": wingmen,
        "domains": domains,
        "martialNames": martial_names,
        "schoolNames": school_names,
        "difficulties": [
            {"id": 1, "kr": "보통"},
            {"id": 2, "kr": "어려움"},
            {"id": 3, "kr": "극난"},
            {"id": 4, "kr": "지옥"},
            {"id": 5, "kr": "홍황"},
        ],
        "animaWeapons": [
            {"id": 1, "kr": "호천안 (昊天眼)"},
            {"id": 2, "kr": "쌍어패 (双鱼佩)"},
            {"id": 3, "kr": "연요호 (炼妖壶)"},
        ],
        "currencies": [
            {"id": 10001, "kr": "영석 (灵石)", "max": 999999999},
            {"id": 10011, "kr": "종문 공헌 (宗门贡献)", "max": 99999999},
            {"id": 10041, "kr": "성주령 (城主令)", "max": 999999},
        ],
        "propertyFields": {"groups": PROPERTY_FIELDS["groups"], "all": flat_props},
        "codexEntries": codex_entries,
        "endgameBuilds": endgame_builds,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Extract Tale of Immortal catalog data")
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--corpus-dir", default=None, type=Path)
    ap.add_argument("--output", default=REPO_ROOT / "src/catalog-data.js", type=Path)
    args = ap.parse_args(argv)

    catalog = build_catalog(args.data_dir, args.corpus_dir)
    payload = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload = re.sub(r"(?i)</(script)", lambda m: "<\\/" + m.group(1), payload)
    js = (
        "(function(root,factory){"
        "if(typeof module==='object'&&module.exports){module.exports=factory();}"
        "else{var d=factory();root.TaleOfImmortalCatalog=d;root.TOICatalog=d;}"
        "}(typeof globalThis!=='undefined'?globalThis:(typeof self!=='undefined'?self:this),function(){"
        "return " + payload + ";"
        "}));\n"
    )
    if EXTERNAL_URL_RE.search(js) is not None:
        raise SystemExit("External URL reference detected in catalog payload")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(js, encoding="utf-8", newline="\n")
    print(
        f"wrote {args.output} ({args.output.stat().st_size} bytes): "
        f"items={len(catalog['items'])}, realms={len(catalog['realms'])}, "
        f"destinies={len(catalog['destinies'])}, sprites={len(catalog['sprites'])}, hearts={len(catalog['hearts'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
