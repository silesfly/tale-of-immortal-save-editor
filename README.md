# 귀곡팔황 (Tale of Immortal) 세이브 에디터 v1.0

귀곡팔황(鬼谷八荒 / *Tale of Immortal*)의 암호화된 세이브 슬롯(`CacheData`, `*.cache`, 전역 `DataGloble.cache`)을 오프라인에서 안전하게 복호화·편집·재암호화하는 한국어 세이브 에디터입니다.

동일한 데이터 규약과 무결성 원칙 아래 **3종 실행 표면**을 제공합니다:
1. **오프라인 단일 HTML (`dist/TaleOfImmortalSaveEditor-v1.0.html`)** — 외부 URL 참조 `0`건, 브라우저 단독 실행 및 **체험용 슬롯 불러오기** 지원
2. **무의존성 Python 3 CLI & 로컬 루프백 서버 (`tale_of_immortal_editor.py`)** — 표준 라이브러리만 사용하는 명령줄 도구 및 CSRF·DNS 리바인딩 방어 로컬 웹 서버
3. **Windows x64 단독 실행 파일 (`dist/TaleOfImmortalSaveEditor-v1.0.exe`)** — `.NET Framework 4.8`(`csc.exe` C# 5.0) + 내장 `WebView2`(`1.0.4258.31`) 기반 설치 불필요 데스크톱 앱

---

## 주요 기능

### 내장 한국어 카탈로그 (`src/catalog-data.js`)
- **아이템 3,222종** (재화·돌파 재료·영과·단약·비급·천재지보·반지·탈것 등 검색 및 추가)
- **수련 경지 44단계** (연기 초기 ~ 등선 후기)
- **선천/후천 운명(기운) 1,129종** (선천기운 최대 9슬롯 및 후천운명 편집)
- **기령 32종 · 도심 21종 · 명우 11종 · 영역 12종**
- **종결 빌드 가이드 6종 · 백과사전 120항목 · 캐릭터 능력치 51개 키**

### 편집 범위 및 원클릭 프리셋 6종
- **기본·경지·세계 일자**: 성/이름, 성별, 경지, 수련 경험치, 연령/수명(개월), 세계 경과일(연·월·일 자동 환산), 난이도, 부활 횟수, 선천신병(`animaWeapons`)
  - 슬롯 헤더(`CacheData`)의 `name`(공백 없는 성+이름 결합), `gradeID`, `worldDay`, `gameLevel`을 자동 동기화하며, `.NET DateTime.Ticks` 64비트 정수(`createTicks`) 정밀도를 무손실 보존합니다.
- **능력치·자질**: 전투 능력치, 6대 영근(`화·수·뢰·풍·토·목`), 6대 무기(`도·창·검·권·장·지`), 6대 기예(`연단·연기·풍수·화부·약재·광재`)
- **재화·소지품**: 영석(`10001`), 종문 공헌(`10011`), 성주령(`10041`) 및 인벤토리 아이템 수량 수정·추가·삭제
- **습득 비급**: 보유 무예·절기·신법·심법·신통 등급(`1~10`), 품질(`1~6`), 숙련도 조정 및 일괄 만렙
- **소속 종문**: 종문 영석, 명성, 인원, 번영도/상한, 충성도(`propertyData.loyal` 및 `propertyData.Loyal` 동시 반영), 약재, 광재, 호산대진 내구도/최대 내구도
- **기령·도심·명우·인연·전역 업적**: 보유 기령 친밀도·경험치·기력, 도심/명우 설정 및 심마 해제, NPC 친밀도, `DataGloble.cache` 전역 업적 일괄 해금
- **원클릭 프리셋 6종**:
  - `rich-cultivator` (만능 재화 충만)
  - `full-recovery` (상태 완전 회복)
  - `omni-aptitude` (12대 자질 극대화)
  - `immortal-stat` (불사 전투원)
  - `martial-perfection` (습득 비급 만렙)
  - `sect-prosperity` (소속 종문 번영)

---

## 세이브 암호화 규약 및 안전성 보장

### 세이브 파일 구조
기본 세이브 경로(Steam 기준):
```text
%USERPROFILE%\AppData\LocalLow\guigugame\guigubahuang\Steam\CacheData\
├── DataGloble.cache                     # 전역 업적 등 계정 공유 데이터
└── 1_xxxxxx\                            # 개별 세이브 슬롯 폴더
    ├── CacheData                        # 슬롯 요약 헤더 (64비트 createTicks 포함)
    ├── CacheFixVer                      # 평문 버전 표식 ("85", 읽기 전용 보존)
    ├── eMZk7avfjaaSiFBwLwtZHg==.cache   # DataWorld (플레이어 ID, 세계 일자, 난이도 등)
    ├── O33a@9fkh++YwffVNeV1RA==.cache   # DataUnit (유닛 능력치, 인벤토리, 운명, 비급, 기령, 관계)
    └── soegnXJ65qU3ZS4O9xLDgg==.cache   # DataBuildSchool (소속 종문 자원 및 속성)
```
- **암·복호화 방식**: `CacheFixVer`를 제외한 세이브 캐시 파일은 21바이트 고정 헤더(`1b8bg-/%ePe]P[-/921CG`) 뒤에 GZip 압축된 UTF-8 JSON 바이트열을 23바이트 순환 키(`5:.A%KL;,.?<aH._=-/DF4s`)로 바이트 단위 가산(`(b + k) & 0xFF`)한 형식입니다.
- **비편집 파일 불변 보존**: `CacheFixVer`와 편집하지 않은 기타 `.cache` 파일은 재인코딩하거나 덮어쓰지 않으며 원본 바이트 그대로 유지합니다.

### 다중 계층 안전 장치
자동 `.backup-*.bak` 생성, SHA-256 검증, 프로세스 가드, 롤백은 **직접 슬롯 저장 모드(Windows 데스크톱 `.exe` 저장, Python 3 CLI `edit`, 로컬 보안 서버 `serve`)**에 적용되며, 단일 파일 변환 명령(`decrypt` / `encrypt`)은 **새 파일 생성 전용**으로 동작해 기존 파일 덮어쓰기 및 기존 세이브 슬롯 폴더 내부 직접 쓰기를 거부합니다. **오프라인 단일 HTML 브라우저 단독 모드**에서는 수정된 `.cache` 파일을 브라우저로 다운로드하므로 수동 백업과 교체는 사용자가 수행합니다.
- **실행 중 게임 감지**: `guigubahuang` 프로세스가 실행 중이면 저장을 차단하여 세이브 파손을 예방합니다(데스크톱 `.exe` · Python CLI `edit` 및 캐시 파일명 `encrypt` · 로컬 서버 `serve` 적용). `--force`(`--ignore-running-game`) 예외 플래그는 **Python CLI `edit` 전용**(로컬 서버 API `force` 필드 포함)이며 **데스크톱 `.exe`는 해당 실행 인수를 지원하지 않습니다**.
- **원본 자동 백업 및 해시 검증**: 덮어쓰기 전 변경 대상 파일마다 `.backup-<타임스탬프>-<식별자>.bak` 백업을 배타 핸들로 생성하고 SHA-256 해시를 대조합니다. (데스크톱 .exe · Python CLI edit · 로컬 서버 serve 슬롯 저장 시)
- **외부 변경 충돌 차단 및 잠금 범위**: 열람 시점의 SHA-256과 디스크 파일 해시가 달라졌으면 부분 쓰기 없이 즉시 거부합니다. Windows(`.exe` 및 Python CLI/서버)는 해시 검증부터 커밋·롤백 완료까지 대상 파일(신규 게시 출력 파일 및 `.backup-*.bak` 백업 파일 포함)의 배타 핸들(`FileShare.None`)을 유지하고 원자적 이름 변경 직전 임시 핸들의 크기·SHA-256을 재검증하여 외부 프로세스의 동시 쓰기·교체를 차단하며 핸들 단위로 복구·삭제를 수행합니다(신규·백업 파일 생성 및 Python 디렉터리 접근 시 고정 디렉터리 핸들 검증 병행). POSIX(Python CLI/서버)는 고정 디렉터리 디스크립터(`O_DIRECTORY | O_NOFOLLOW`), `0700` 비공개 스테이징 디렉터리(`mkdir` 직후 아이노드·열린 FD·빈 디렉터리 대조 후 권한 설정)와 열린 임시 FD 크기·SHA-256 게시 직전 재검증, 권고적 파일 잠금(`flock`), `os.link` 직후 게시 소유권 즉시 등록, 그리고 커밋·롤백(기존 파일 복원·신규 게시 파일 삭제) 및 스테이징 디렉터리 삭제(`rmdir`) 직전의 아이노드(`st_dev, st_ino`; 파일은 링크 수·SHA-256 포함) 소유권 재검증을 수행합니다(단, POSIX 권고적 잠금을 따르지 않는 비협조적 외부 프로세스의 커밋 직후 동시 덮어쓰기, `mkdir` 직후 초기 아이노드 조회 전, 또는 소유권 검증 직후와 `os.replace`/`unlink`/`rmdir` 사이의 극미세 교체 경합은 OS 특성상 커널 수준에서 강제 차단되지 않습니다).
- **다중 파일·단일 출력 롤백 시도 및 백업·외부 파일 보존**: 다중 파일 커밋, 비편집 슬롯 복사본 생성(`edit -o`), 또는 단일 출력 파일 게시(`decrypt`·`encrypt`, `os.link` 직후 스테이징 정리 포함) 도중 오류가 발생하면 이미 반영된 파일을 자동 원상복구(기존 파일 복원·신규 게시/복사 파일 삭제)합니다. `.backup-*.bak` 백업 파일, `.tmp-*` 임시 파일, POSIX `.toi-stage-*` 스테이징 디렉터리 역시 준비(스테이징 디렉터리 초기 아이노드 바인딩 이후)·게시·커밋·정리 구간에서 Windows 배타 삭제 핸들(파일 ID 대조) 또는 POSIX 아이노드(`st_dev, st_ino`; 파일은 링크 수·의도한 쓰기 접두부/전체 SHA-256 포함) 소유권 검증을 통과한 경우에만 삭제하며, 게시 전후 정리 오류도 삼키지 않고 보고합니다. 만약 디스크 삭제 실패나 준비·게시·커밋 전후 외부 프로세스의 동시 수정·교체(소유권 불일치·검증된 배타 핸들 부재) 등으로 실패 정리 또는 자동 롤백이 실패·중단할 경우, 외부 수정·교체 파일(및 해당 POSIX `.toi-stage-*` 스테이징 디렉터리)을 덮어쓰거나 삭제하지 않고(기존 파일은 원본 `.bak` 백업 파일도 삭제하지 않은 채 보존) 잔존 대상 경로가 포함된 명시적 정리·롤백 예외를 최초 예외와 연결해 반환하여 수동 복구가 가능하도록 합니다.
- **경로 보안**: 읽기·쓰기 전 경로에서 고정 디렉터리·핸들 검증을 통해 심볼릭 링크, 디렉터리 정션(재분석 지점), 하드링크(`nNumberOfLinks > 1`), NTFS 대체 데이터 스트림(`:`), UNC 네트워크 경로, Windows 예약 장치명(`CON`, `NUL` 등)을 거부합니다.

---

## 사용 방법

### 1. Windows 데스크톱 실행 파일 (`.exe`)
1. 게임을 완전히 종료한 뒤 `dist/TaleOfImmortalSaveEditor-v1.0.exe`를 실행합니다.
2. 상단의 **슬롯 폴더 열기** 버튼을 눌러 편집할 슬롯 폴더(예: `1_xxxxxx`)를 선택합니다(상위 폴더의 `DataGloble.cache`도 자동 탐색).
3. 원하는 항목이나 프리셋을 적용한 뒤 **자동 백업 저장**을 클릭합니다.

### 2. 오프라인 단일 HTML
- `dist/TaleOfImmortalSaveEditor-v1.0.html`을 최신 Chromium 계열 브라우저에서 열어 **슬롯 폴더 선택**/**파일 직접 선택** 후 **수정본 내보내기**, 또는 상단의 **체험용 슬롯 불러오기**로 즉시 기능을 확인할 수 있습니다(브라우저 모드의 폴더 선택은 선택한 폴더 내부 파일만 읽으며, 상위 폴더의 `DataGloble.cache`를 함께 편집하려면 **파일 직접 선택**으로 함께 열거나 `.exe` / 로컬 보안 서버 모드를 사용하세요).
- **수정본 내보내기**는 브라우저를 통해 암호화된 `.cache` 파일을 다운로드하며 로컬 디스크를 직접 수정하지 않으므로, 파일 교체 전에 원본 슬롯 폴더를 수동으로 백업하세요.

### 3. Python 3 CLI 및 로컬 보안 서버
외부 패키지 설치 없이 Python 3 표준 라이브러리만으로 동작합니다.

```bash
# 슬롯 요약 정보 및 무결성 검증
python3 tale_of_immortal_editor.py inspect /path/to/CacheData/1_xxxxxx --json
python3 tale_of_immortal_editor.py validate /path/to/CacheData/1_xxxxxx --json

# 사용 가능한 프리셋 목록 확인
python3 tale_of_immortal_editor.py presets

# 비파괴 출력 폴더(-o)로 프리셋·능력치·아이템 편집 저장
python3 tale_of_immortal_editor.py edit /path/to/CacheData/1_xxxxxx \
  -o /path/to/output_slot \
  --preset rich-cultivator \
  --preset sect-prosperity \
  --grade 34 \
  --set-prop qt=999 \
  --add-item 10041:50 \
  --max-martials

# 단일 캐시 파일 JSON 복호화 및 재암호화 (새 파일 생성 전용 · 기존 파일/슬롯 폴더 덮어쓰기 차단)
python3 tale_of_immortal_editor.py decrypt /path/to/CacheData/1_xxxxxx/CacheData -o header.json --pretty
python3 tale_of_immortal_editor.py encrypt header.json -o CacheData.rebuilt

# 로컬 루프백(127.0.0.1) 보안 웹 에디터 실행
python3 tale_of_immortal_editor.py serve --save-dir /path/to/CacheData --port 8765
```

---

## 빌드 및 자동 검증

```bash
# 단일 오프라인 HTML 번들 생성
python3 build.py

# Windows x64 .NET Framework 4.8 + 내장 WebView2 단일 실행 파일 빌드 (Windows)
python build.py --exe --webview2 <WebView2_SDK_폴더>

# Node 코덱·코어·카탈로그·번들 HTML 검증
node tests/test_editor.cjs

# Python CLI·보안 가드·루프백 서버 단위 테스트
python3 -B -m unittest discover -s tests -v

# Windows SaveStore 원자적 파일 저장소 테스트 및 WebView2 무인 자가 검증
SaveStoreTests.exe <새_임시_폴더>
TaleOfImmortalSaveEditor-v1.0.exe --self-test <새_검증_폴더> [<시드_슬롯_폴더>]
```

---

## 라이선스

이 프로젝트는 [MIT License](./LICENSE)에 따라 배포됩니다. Windows 실행 파일에 내장되는 Microsoft Edge WebView2 SDK 재배포 구성 요소의 라이선스는 리소스 내 `WebView2-LICENSE.txt`를 따릅니다.
